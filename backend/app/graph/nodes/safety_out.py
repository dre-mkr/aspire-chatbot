"""The last thing that touches an outbound message. Six gates, in order.

    a. length cap by age band
    b. vocabulary, against the band's banned list
    c. PII scrub
    d. link and image stripping, for children
    e. quick-replies presence, during a lesson
    f. locale

The order is not arbitrary and changing it changes behaviour. Length runs first
because it is the gate most likely to trigger a rewrite, and a rewrite has to be
re-checked by everything after it -- running vocabulary first would mean
checking text the model is about to replace. PII runs after the rewrites,
because a rewrite can reintroduce a number the model saw earlier in the thread.
Links are stripped after PII so that a redacted e-mail address cannot leave a
`mailto:` behind. Locale is last because it is the only gate that judges the
whole finished message.

## Widgets are split out before any of it, and put back after

A lesson turn can carry a composed widget between `⟦widget⟧` markers. Every
gate here runs on the PROSE only, with the blocks lifted out first
(`widgets/sentinel.py`) and returned afterwards.

Not a special case for tidiness -- without it the widget feature cannot work at
all. A composed widget is a few hundred characters of JSON, so gate (a) counts
it against a thirty-five word cap, decides the reply is four hundred words
long, and re-prompts the model to shorten it. The model shortens it by deleting
the widget. What reaches the child is prose, and what reaches the log is a
length violation, and neither says that a widget was destroyed.

The prose is still gated in full, so nothing is weakened: a widget has its own
seven gates in `widgets/validate.py`, and those check exactly the things these
cannot -- band-permitted primitive, control count, formula domain, copy against
the band's word list.

## What may use a model and what may not

Detection is deterministic in every gate. Counting words is arithmetic; finding
a national ID is a regex; a banned term is a set membership test. None of that
is a judgement call and none of it may become one -- a model asked "is this too
long for a six-year-old?" gives a different answer on Tuesday.

Two gates use a model for the *remedy*, once each: a message over the cap is
re-prompted with a shorten instruction, and a lesson turn with no chips is
re-prompted for chips. A second failure is handled deterministically -- truncate
at the last complete sentence, or fall back to a single chip -- because a second
re-prompt is a third model call on a turn a child is waiting through, and the
deterministic answer is always available.

## This node is not skippable

Every path through `main_graph` ends here, including the refusal paths, and
that is enforced by the graph having exactly one edge into `persist` and it
coming from this node. A router that could bypass this would be a router that
could serve unbounded, unfiltered text to a six-year-old.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import AIMessage

from app.graph.state import AspireState, band_index
from app.safety import pii, vocab
from app.widgets import sentinel

logger = logging.getLogger(__name__)

#: The three names the lesson subgraph is registered under.
#:
#: Gate (e) used to name `learn_agent` alone, which meant a guardian preview and
#: a signed-out sample ran the identical machine with the chip requirement
#: switched off -- and those are precisely the two audiences being shown what
#: the product is like.
LEARNING_AGENTS: frozenset[str] = frozenset(
    {"learn_agent", "learning_preview", "learning_sample"}
)

#: Words allowed per answer, by band. `None` means no cap.
#:
#: These are reading-stamina numbers rather than comprehension numbers. A
#: six-year-old can follow an idea for a long time; they cannot follow a wall of
#: text. Thirty-five words is roughly three short sentences, which is what a
#: mascot turn should be before it hands the conversation back.
WORD_CAPS: dict[str, int | None] = {
    "5-8": 35,
    "9-12": 70,
    "13-15": 120,
    "16-18": 180,
    "adult": None,
}

#: The same ceiling, for a turn that is TEACHING rather than talking.
#:
#: A lesson is a different kind of message from a mascot's conversational turn and
#: needs a different ceiling. Thirty-five words is three short sentences: correct
#: for "good question -- back to our snow cone money", and below the FLOOR of an
#: explanation. A concept explained to a six-year-old in thirty-five words is a
#: definition read aloud, which is precisely the "thin and generic" report that
#: opened Track L.
#:
#: The reading-stamina argument still holds and these are not generous: ninety
#: words at 5-8 is six or seven short sentences with an example in the middle,
#: read once, about something they asked about. What it is not is a wall of text.
#:
#: These MUST equal `agents/learn/contract.CONTRACTS[band].max_words`. A prompt
#: that asks for more words than this gate permits produces a re-prompt on every
#: single turn -- a second model call, forever, caused by two constants drifting
#: apart. `tests/learning/test_contract.py` pins them together.
LESSON_WORD_CAPS: dict[str, int | None] = {
    "5-8": 90,
    "9-12": 120,
    "13-15": 180,
    "16-18": 180,
    "adult": 220,
}


def cap_for(band: str, agent: str | None) -> int | None:
    """The word ceiling for this turn: the lesson cap when teaching, else the chat cap."""
    table = LESSON_WORD_CAPS if agent in LEARNING_AGENTS else WORD_CAPS
    return table.get(band)

#: The band at and above which links may be shown, and the personas that never
#: see them regardless.
#:
#: Gate (d) is "persona is stella, or persona is orion and the band is under
#: 16". Written as data rather than as a condition so that the answer to "does
#: this child see links?" is a lookup somebody can read.
_NO_LINK_PERSONAS = frozenset({"stella"})
_ORION_LINK_BAND = "16-18"

#: How many chips a lesson turn must offer, and how long each may be.
QUICK_REPLY_MIN = 2
QUICK_REPLY_MAX = 4
QUICK_REPLY_MAX_WORDS = 4

#: The last-resort chip, when a re-prompt still produced nothing. One option,
#: because a dead end is the failure being prevented and one way forward
#: prevents it.
_FALLBACK_CHIP: dict[str, str] = {
    "en": "Keep going",
    "es": "Seguimos",
    "fr": "On continue",
}

#: A callable that asks the model to try again. Injected rather than imported so
#: the gates are testable without a network, and so the eval harness can count
#: re-prompts without patching a module global.
Reprompt = Callable[[str, str], Awaitable[str]]


# ── gate a: length ───────────────────────────────────────────────────────────


def word_count(text: str) -> int:
    """Words, by whitespace.

    Not tokens and not characters. The cap is about how much a child has to
    read, and whitespace-separated runs are what a reader experiences as words.
    """
    return len(text.split())


def over_cap(text: str, band: str, agent: str | None = None) -> bool:
    """Whether this reply exceeds the ceiling for its band and its kind of turn.

    `agent` defaults to None, which selects the conversational caps -- so every
    existing caller keeps the behaviour it had, and only a turn that says it is
    teaching gets the lesson ceiling.
    """
    cap = cap_for(band, agent)
    return cap is not None and word_count(text) > cap


#: Sentence terminators, including the ones that end a spoken sentence in the
#: three shipped locales.
_SENTENCE_END = re.compile(r"[.!?…]['\")\]]*\s")


def truncate_at_sentence(text: str, max_words: int) -> str:
    """The longest prefix within the cap that ends on a complete sentence.

    Falls back to a hard word cut with an ellipsis only when there is no
    sentence boundary at all inside the budget -- one very long first sentence.
    Cutting mid-sentence is bad; cutting mid-word is worse, and leaving a
    six-year-old with 300 words is worse than both.
    """
    words = text.split()
    if len(words) <= max_words:
        return text

    budget = " ".join(words[:max_words])
    # Search the ORIGINAL text up to the budget's length so the terminator's
    # trailing whitespace is present to match against.
    window = text[: len(budget) + 1]
    ends = list(_SENTENCE_END.finditer(window))
    if ends:
        return window[: ends[-1].end()].strip()
    return budget.rstrip(",;:") + "…"


def shorten_instruction(band: str, current: int, agent: str | None = None) -> str:
    """The re-prompt for gate (a). Specific, with the number in it.

    "Be briefer" produces a message that is 10% shorter. Naming the cap and the
    current length produces one that fits, because the model can count.
    """
    cap = cap_for(band, agent)
    return (
        f"That reply is {current} words. A learner in the {band} band can take "
        f"at most {cap}. Say the same thing in {cap} words or fewer. Keep the "
        "warmth and keep the question at the end -- cut the explanation, not "
        "the invitation to reply."
    )


# ── gate d: links and images ─────────────────────────────────────────────────

#: Markdown images first, then markdown links, then bare URLs and schemes.
#: Ordered because `![alt](url)` also matches the link pattern, and stripping
#: the link first would leave a stray `!`.
_IMAGE_MD = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_MD = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BARE_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_SCHEME = re.compile(r"\b(?:mailto|tel|sms|data|javascript):\S+", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def strips_links(persona: str, band: str) -> bool:
    """Whether this reader gets links at all.

    Stella never. Orion below 16-18 never. Everyone else yes.

    The rule is about who can evaluate a destination, not about who can read.
    A link in a chat window is an instruction to leave the product, and a
    thirteen-year-old following one has left every protection this file
    represents.
    """
    if persona in _NO_LINK_PERSONAS:
        return True
    if persona == "orion":
        return band_index(band) < band_index(_ORION_LINK_BAND)
    return False


def strip_links(text: str) -> str:
    """Remove links and images, keeping the words that were linked.

    Keeping the anchor text matters: "read the [eligibility rules](...)" becomes
    "read the eligibility rules", which is still a sentence. Deleting the whole
    phrase would leave "read the", which reads as a bug.
    """
    out = _IMAGE_MD.sub("", text)
    out = _LINK_MD.sub(r"\1", out)
    out = _BARE_URL.sub("", out)
    out = _SCHEME.sub("", out)
    out = _HTML_TAG.sub("", out)
    # Collapse the double spaces the deletions leave, without touching newlines.
    out = re.sub(r"[ \t]{2,}", " ", out)
    return re.sub(r" +([.,!?;:])", r"\1", out).strip()


# ── gate e: quick replies ────────────────────────────────────────────────────


def quick_replies_ok(replies: list[str]) -> bool:
    """Whether a lesson turn's chips are usable.

    Count and length both. Two chips of nine words each are not a tap-first
    interface -- they are a reading task with extra steps.
    """
    if not QUICK_REPLY_MIN <= len(replies) <= QUICK_REPLY_MAX:
        return False
    return all(0 < word_count(reply) <= QUICK_REPLY_MAX_WORDS for reply in replies)


QUICK_REPLY_INSTRUCTION = (
    f"End with {QUICK_REPLY_MIN} to {QUICK_REPLY_MAX} tappable options. Each "
    f"must be at most {QUICK_REPLY_MAX_WORDS} words. Put them on their own "
    "lines at the very end, each starting with '- '. They are what the learner "
    "taps to reply, so write them in their voice, not yours."
)

_CHIP_LINE = re.compile(r"^\s*[-*•]\s+(.{1,60})\s*$", re.MULTILINE)


def parse_chips(text: str) -> tuple[str, list[str]]:
    """Pull a trailing bulleted list off a message. Returns `(prose, chips)`.

    Only a run of bullets at the very END counts. A bulleted list in the middle
    of an explanation is content, and hoisting it into chips would delete the
    explanation's body and offer its steps as things to tap.
    """
    lines = text.rstrip().split("\n")
    chips: list[str] = []
    while lines:
        match = _CHIP_LINE.match(lines[-1])
        if not match:
            break
        chips.insert(0, match.group(1).strip())
        lines.pop()
    return "\n".join(lines).strip(), chips


# ── gate f: locale ───────────────────────────────────────────────────────────

#: Very common function words, per locale. Detection by stopword frequency
#: rather than by a library, for the same reason the PII patterns are regexes:
#: it runs on every message, it has to be explainable, and the decision it
#: drives is "ask the model to try again", which is cheap to get wrong in the
#: false-positive direction and is re-checked afterwards.
#:
#: The lists are deliberately LONG. A short list of the ten commonest words in
#: each language does not separate Spanish from French, because they share most
#: of them -- `un`, `que`, `de`, `en`, `la`, `tu` all count for both. The
#: separation comes from the words that differ, so the lists carry pronouns,
#: auxiliaries and prepositions rather than only articles.
_STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        "the a an and is are was were you your yours that this it its to of for "
        "we can could what how with have has had do does did not on in but all "
        "very when if or where be been there also some more out up get make one "
        "i he she they them their would will about from".split()
    ),
    "es": frozenset(
        "el la los las un una unos unas y o es son era eran tu tus su sus mi mis "
        "que esto eso esta este para por con de del al en no como qué cómo "
        "puedes puede pueden tiene tienes tener hacer hace más menos pero sobre "
        "todo muy cuando si donde ser hay ya también yo él ella nosotros ustedes "
        "quiero quieres".split()
    ),
    "fr": frozenset(
        "le la les un une des du au aux et ou est sont était étaient ton tes ta "
        "son sa ses mon ma mes que qui ce cette cela pour par avec de en ne pas "
        "comme quoi comment peux peut peuvent as ai avez faire fait plus moins "
        "mais sur tout très quand si où être il elle nous vous ils elles je tu "
        "dans veux veut leur".split()
    ),
}

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def detect_locale(text: str) -> str | None:
    """Which of the three shipped locales this reads as, or None if unsure.

    None on anything short. A four-word reply has no reliable signal, and
    re-prompting a correct message because it was brief is exactly the false
    positive that makes a gate get switched off.
    """
    words = [word.lower() for word in _WORD.findall(text)]
    if len(words) < 8:
        return None

    scores = {
        locale: sum(1 for word in words if word in stopwords)
        for locale, stopwords in _STOPWORDS.items()
    }
    best = max(scores, key=lambda locale: scores[locale])
    ordered = sorted(scores.values(), reverse=True)
    # A clear winner only. Two locales within one hit of each other means the
    # signal is noise -- short technical text, or a sentence of proper nouns.
    if ordered[0] == 0 or ordered[0] - ordered[1] < 2:
        return None
    return best


LOCALE_NAMES = {"en": "English", "es": "Spanish", "fr": "French"}


def locale_instruction(locale: str) -> str:
    name = LOCALE_NAMES.get(locale, "English")
    return (
        f"Answer in {name}. The learner is having this conversation in {name} "
        "and your last reply was in another language. Say the same thing again, "
        f"in {name}."
    )


# ── the node ─────────────────────────────────────────────────────────────────


def _text_of(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def make_safety_out(reprompt: Reprompt | None = None):
    """Build the outbound gate.

    `reprompt` may be None, and then both remedial gates fall straight through
    to their deterministic fallback. That is the shape the unit tests use, and
    it is also a legitimate production configuration: a deployment that would
    rather truncate than pay a second model call sets it to None and loses
    nothing but polish.
    """

    async def safety_out(state: AspireState) -> dict[str, Any]:
        messages = state.get("messages", [])
        if not messages:
            return {}
        last = messages[-1]
        if getattr(last, "type", None) != "ai":
            # Nothing outbound this turn -- an interrupted graph waiting on an
            # upload, for instance. There is nothing to gate.
            return {}

        band = state.get("age_band", "adult")
        persona = state.get("persona", "")
        # Read once, used by gate (a) to pick the ceiling and by gate (e) to
        # decide whether chips are required. One read rather than two, because
        # the two gates disagreeing about whether this is a lesson would produce
        # a turn held to conversational length and required to offer chips.
        agent = state.get("active_agent")
        locale = state.get("locale", "en")
        original = _text_of(last)
        replies = list(state.get("quick_replies") or [])
        report: dict[str, Any] = {}

        # Widgets out, before anything measures or rewrites. `text` is prose
        # from here to the end of the node, and every gate below is written as
        # though widgets do not exist -- which is the point of doing it here.
        text, widgets = sentinel.split(original)
        prose_in = text
        if widgets:
            report["widgets_carried"] = len(widgets)

        # ── (a) length ──────────────────────────────────────────────────────
        if over_cap(text, band, agent):
            report["length_violation"] = word_count(text)
            if reprompt is not None:
                text = await reprompt(shorten_instruction(band, word_count(text), agent), text)
            if over_cap(text, band, agent):
                cap = cap_for(band, agent)
                assert cap is not None  # `over_cap` is False when the cap is None
                logger.info(
                    "Truncating a %s-band reply at the last complete sentence "
                    "after a re-prompt left it at %d words (cap %d).",
                    band,
                    word_count(text),
                    cap,
                )
                text = truncate_at_sentence(text, cap)
                report["length_truncated"] = True

        # ── (b) vocabulary ──────────────────────────────────────────────────
        violations = vocab.check(text, band)
        if violations:
            report["vocab_violations"] = sorted({v.term for v in violations})
            if reprompt is not None:
                text = await reprompt(vocab.explain(violations, band), text)
                # Re-checked, and a second failure is NOT re-prompted again. The
                # remaining terms are removed by hand instead: a banned word
                # reaching a nine-year-old is the failure this gate exists to
                # prevent, and it must not depend on the model complying.
                remaining = vocab.check(text, band)
                if remaining:
                    report["vocab_stripped"] = sorted({v.term for v in remaining})
                    for violation in reversed(remaining):
                        text = text[: violation.start] + text[violation.end :]
                    text = re.sub(r"\s{2,}", " ", text).strip()
            else:
                for violation in reversed(violations):
                    text = text[: violation.start] + text[violation.end :]
                text = re.sub(r"\s{2,}", " ", text).strip()
                report["vocab_stripped"] = report["vocab_violations"]

            # A rewrite can push the reply back over the cap. Cheaper to
            # re-truncate deterministically than to loop the model again.
            if over_cap(text, band, agent):
                cap = cap_for(band, agent)
                assert cap is not None
                text = truncate_at_sentence(text, cap)

        # ── (c) PII ─────────────────────────────────────────────────────────
        kinds = pii.kinds_in(text)
        if kinds:
            report["pii_redacted"] = kinds
            logger.warning(
                "Outbound message for session %s contained %s; redacted before "
                "sending.",
                state.get("session_id"),
                ", ".join(kinds),
            )
            text = pii.redact(text)

        # ── (d) links and images ────────────────────────────────────────────
        if strips_links(persona, band):
            stripped = strip_links(text)
            if stripped != text:
                report["links_stripped"] = True
                text = stripped

        # ── (e) quick replies, during a lesson ──────────────────────────────
        if agent in LEARNING_AGENTS:
            # The model may have written its chips as a trailing bulleted list
            # rather than filling `quick_replies`. Harvest them before deciding
            # anything is missing -- and always remove them from the prose,
            # because leaving them there renders the options twice.
            prose, harvested = parse_chips(text)
            if harvested:
                text = prose
                if not replies:
                    replies = harvested

            if not quick_replies_ok(replies):
                report["quick_replies_missing"] = True
                if reprompt is not None:
                    retried = await reprompt(QUICK_REPLY_INSTRUCTION, text)
                    prose, harvested = parse_chips(retried)
                    if quick_replies_ok(harvested):
                        text, replies = prose, harvested
                    else:
                        report["quick_replies_fallback"] = True
                        replies = [_FALLBACK_CHIP.get(locale, _FALLBACK_CHIP["en"])]
                else:
                    report["quick_replies_fallback"] = True
                    replies = [_FALLBACK_CHIP.get(locale, _FALLBACK_CHIP["en"])]

        # ── (f) locale ──────────────────────────────────────────────────────
        detected = detect_locale(text)
        if detected is not None and detected != locale:
            report["locale_mismatch"] = detected
            logger.info(
                "Reply for session %s read as %s but the conversation is %s.",
                state.get("session_id"),
                detected,
                locale,
            )
            if reprompt is not None:
                retried = await reprompt(locale_instruction(locale), text)
                # Accepted only if it actually moved. A second wrong-language
                # reply is served rather than truncated: an answer in the wrong
                # language is comprehensible to somebody, and no answer is
                # comprehensible to nobody.
                if detect_locale(retried) in (locale, None):
                    text = retried
                    # One last length check -- the retry is a fresh generation.
                    if over_cap(text, band, agent):
                        cap = cap_for(band, agent)
                        assert cap is not None
                        text = truncate_at_sentence(text, cap)
                else:
                    report["locale_unfixed"] = True

        flags = dict(state.get("safety_flags") or {})
        if report:
            flags["outbound"] = report

        # Widgets back in. When no gate touched the prose the ORIGINAL string is
        # restored verbatim -- markers where the model put them, mid-paragraph
        # if that is where it put them -- so the common case pays nothing for
        # having been split. Only a rewritten reply moves its widgets to the end,
        # and only because there is no longer a sentence to anchor them to.
        if widgets:
            text = original if text == prose_in else sentinel.reattach(text, widgets)

        update: dict[str, Any] = {"safety_flags": flags, "quick_replies": replies}
        if text != original:
            # Rewritten in place, keeping the message id, so `add_messages`
            # REPLACES the message rather than appending a second copy. Without
            # the id the transcript would carry both the unsafe original and its
            # corrected version -- and the unsafe one would be the one the model
            # reads back next turn.
            update["messages"] = [AIMessage(content=text, id=getattr(last, "id", None))]
        return update

    return safety_out
