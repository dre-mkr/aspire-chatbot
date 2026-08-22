"""The last thing that touches an outbound message."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, Final

from langchain_core.messages import AIMessage

from app import timing
from app.graph.nodes.safety_in import latest_user_text
from app.graph.state import AspireState, band_index
from app.safety import pii, vocab
from app.widgets import sentinel
from app.messages import text_of

logger = logging.getLogger(__name__)

#: The three names the lesson subgraph is registered under.
LEARNING_AGENTS: frozenset[str] = frozenset(
    {"learn_agent", "learning_preview", "learning_sample"}
)

#: Words allowed per answer, by band.
WORD_CAPS: dict[str, int | None] = {
    "5-8": 35,
    "9-12": 70,
    "13-15": 120,
    "16-18": 180,
    "adult": None,
}

#: The same ceiling, for a turn that is TEACHING rather than talking.
LESSON_WORD_CAPS: dict[str, int | None] = {
    "5-8": 90,
    "9-12": 120,
    "13-15": 180,
    "16-18": 180,
    "adult": 220,
}

#: The three names the Q&A subgraph is registered under.
QA_AGENTS: frozenset[str] = frozenset(
    {"qa_agent", "qa_agent_limited", "qa_agent_public"}
)

#: The ceiling for a FACTUAL answer, which needs room for conditions, amounts and steps.
QA_WORD_CAPS: dict[str, int | None] = {
    "5-8": 120,
    "9-12": 180,
    "13-15": 280,
    "16-18": 400,
    "adult": None,
}


#: The ceiling for a turn that is TELLING A STORY.
#:
#: A story needs its own table because none of the others fit: a five-year-old's
#: plain-chat cap is 35 words, which truncates a story mid-sentence, and
#: `truncate_at_sentence` does it silently -- the build passes, the tests pass,
#: and the reader gets half a story. That is the likeliest way this feature
#: could have shipped broken.
#:
#: Still capped, and not generously. A story a child has to scroll is not a
#: story they will finish, and the per-persona shapes in `qa/nodes.py` already
#: ask for five or six sentences at the youngest band; this is the backstop for
#: when the model ignores them.
STORY_WORD_CAPS: dict[str, int | None] = {
    "5-8": 160,
    "9-12": 240,
    "13-15": 340,
    "16-18": 420,
    "adult": 450,
}


def cap_for(band: str, agent: str | None, *, story: bool = False) -> int | None:
    """The word ceiling for this turn: story, lesson, QA, or plain chat."""
    if story:
        table = STORY_WORD_CAPS
    elif agent in LEARNING_AGENTS:
        table = LESSON_WORD_CAPS
    elif agent in QA_AGENTS:
        table = QA_WORD_CAPS
    else:
        table = WORD_CAPS
    return table.get(band)

#: The band at and above which links may be shown, and the personas that never see them regardless.
# `kaleb` joins `stella` because he IS the older half of what `stella` used to
# be. Leaving him out would have handed a nine-year-old the link strip that the
# same reader was refused the day before, purely because his key changed.
_NO_LINK_PERSONAS = frozenset({"stella", "kaleb"})
_ORION_LINK_BAND = "16-18"

#: How many chips a lesson turn must offer, and how long each may be.
QUICK_REPLY_MIN = 2
QUICK_REPLY_MAX = 4
QUICK_REPLY_MAX_WORDS = 4

#: The last-resort chip, when a re-prompt still produced nothing.
_FALLBACK_CHIP: dict[str, str] = {
    "en": "Keep going",
    "es": "Seguimos",
    "fr": "On continue",
}

#: A callable that asks the model to try again.
Reprompt = Callable[[str, str], Awaitable[str]]


# ── gate a: length ───────────────────────────────────────────────────────────


def word_count(text: str) -> int:
    """Words, by whitespace."""
    return len(text.split())


def over_cap(
    text: str, band: str, agent: str | None = None, *, story: bool = False
) -> bool:
    """Whether this reply exceeds the ceiling for its band and its kind of turn."""
    cap = cap_for(band, agent, story=story)
    return cap is not None and word_count(text) > cap


#: Sentence terminators, including the ones that end a spoken sentence in the three shipped locales.
_SENTENCE_END = re.compile(r"[.!?…]['\")\]]*\s")


def truncate_at_sentence(text: str, max_words: int) -> str:
    """The longest prefix within the cap that ends on a complete sentence."""
    words = text.split()
    if len(words) <= max_words:
        return text

    budget = " ".join(words[:max_words])
    # Search the original text, so the terminator's trailing whitespace is there to match.
    window = text[: len(budget) + 1]
    ends = list(_SENTENCE_END.finditer(window))
    if ends:
        return window[: ends[-1].end()].strip()
    return budget.rstrip(",;:") + "…"


def shorten_instruction(
    band: str, current: int, agent: str | None = None, *, story: bool = False
) -> str:
    """The re-prompt for gate (a)."""
    cap = cap_for(band, agent, story=story)
    return (
        f"That reply is {current} words. A learner in the {band} band can take "
        f"at most {cap}. Say the same thing in {cap} words or fewer. Keep the "
        "warmth and keep the question at the end -- cut the explanation, not "
        "the invitation to reply."
    )


# ── gate d: links and images ─────────────────────────────────────────────────

#: Markdown images first, then markdown links, then bare URLs and schemes.
_IMAGE_MD = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_MD = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BARE_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_SCHEME = re.compile(r"\b(?:mailto|tel|sms|data|javascript):\S+", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def strips_links(persona: str, band: str) -> bool:
    """Whether this reader gets links at all."""
    if persona in _NO_LINK_PERSONAS:
        return True
    if persona == "orion":
        return band_index(band) < band_index(_ORION_LINK_BAND)
    return False


def strip_links(text: str) -> str:
    """Remove links and images, keeping the words that were linked."""
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
    """Whether a lesson turn's chips are usable."""
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
    """Pull a trailing bulleted list off a message."""
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

#: Very common function words, per locale.
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
    """Which of the three shipped locales this reads as, or None if unsure."""
    words = [word.lower() for word in _WORD.findall(text)]
    if len(words) < 8:
        return None

    scores = {
        locale: sum(1 for word in words if word in stopwords)
        for locale, stopwords in _STOPWORDS.items()
    }
    best = max(scores, key=lambda locale: scores[locale])
    ordered = sorted(scores.values(), reverse=True)
    # A clear winner only.
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


#: Bands whose card forbids a figure outright.
#:
#: 5-8 ONLY, and the narrowness is the point. `stella.5-8.md` red line 3 reads
#: "NEVER state a rate, a percentage, a balance or a projected amount -- not even
#: a sourced one. This reader cannot check it and does not need it." Kaleb's 9-12
#: card says the opposite in as many words -- "Plain digits. EC dollars as EC$.
#: Examples in sums between five and three hundred" -- so a gate that caught him
#: would be breaking his card to enforce hers.
_NO_FIGURE_BANDS: Final[frozenset[str]] = frozenset({"5-8"})

#: A money amount or a percentage. Deliberately narrow.
#:
#: Bare small integers are NOT matched: "three rounds", "two jars" and "you are 7"
#: are ordinary language at this age, and a gate that ate them would be worse than
#: the thing it is guarding.
_FIGURE = re.compile(
    r"(?:EC\s?\$|US\s?\$|\$)\s?[\d,]+(?:\.\d+)?"   # EC$1,000
    r"|\b\d+(?:\.\d+)?\s?(?:%|per\s?cent|percent)"     # 5%, 5 per cent
    r"|\b\d[\d,]{2,}(?:\.\d+)?\b",                     # 1,000 / 1000 bare
    re.IGNORECASE,
)


def has_figure(text: str) -> bool:
    """Whether an answer names a money amount or a percentage."""
    return bool(_FIGURE.search(text))


def figure_instruction() -> str:
    """The reprompt. Names the rule rather than the offending string."""
    return (
        "Remove every money amount and every percentage from the answer. Say the "
        "idea in words instead -- 'the bank adds a little', not a figure. If the "
        "reader asked for an amount, say plainly that it is something a grown-up "
        "should tell them, as a choice rather than as something you do not know."
    )


def make_safety_out(reprompt: Reprompt | None = None):
    """Build the outbound gate."""

    async def safety_out(state: AspireState) -> dict[str, Any]:
        messages = state.get("messages", [])
        if not messages:
            return {}
        last = messages[-1]
        if getattr(last, "type", None) != "ai":
            # Nothing outbound this turn -- an interrupted graph waiting on an upload, for instance.
            return {}

        band = state.get("age_band", "adult")
        persona = state.get("persona", "")
        # Read once: gate (a) picks the ceiling, gate (e) decides whether chips are required.
        agent = state.get("active_agent")
        locale = state.get("locale", "en")
        original = text_of(last)
        replies = list(state.get("quick_replies") or [])
        report: dict[str, Any] = {}

        # Widgets out, before anything measures or rewrites.
        text, widgets = sentinel.split(original)
        prose_in = text
        if widgets:
            report["widgets_carried"] = len(widgets)

        # ── (a) length ──────────────────────────────────────────────────────
        # A story is a different KIND of turn, so it is measured against a
        # different table. Without this the youngest band's 35-word chat cap
        # cuts every story mid-sentence, silently.
        story = bool(state.get("story_topic"))
        if over_cap(text, band, agent, story=story):
            report["length_violation"] = word_count(text)
            if reprompt is not None:
                timing.note_reprompt("length")
                text = await reprompt(
                    shorten_instruction(band, word_count(text), agent, story=story), text
                )
            if over_cap(text, band, agent, story=story):
                cap = cap_for(band, agent, story=story)
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

        # ── (a2) figures, at the youngest band only ─────────────────────────
        # `stella.5-8.md` red line 3 forbids a rate, a percentage, a balance or a
        # projected amount, "not even a sourced one" -- and until now that rule
        # lived ONLY in the prompt. Observed on production 22 Aug: the same
        # question produced "the bank may add EC$20 after one year" on one run and
        # a figure-free answer on the next. A red line the model follows most of
        # the time is not a red line.
        #
        # Every other rule on that card has a backstop: the vocabulary ladder has
        # `vocab.check`, the links have `_NO_LINK_PERSONAS`. This is that, for the
        # one rule that had none.
        if band in _NO_FIGURE_BANDS and has_figure(text):
            report["figure_violation"] = True
            if reprompt is not None:
                timing.note_reprompt("figure")
                text = await reprompt(figure_instruction(), text)
            if has_figure(text):
                # The reprompt did not clear it. Redacting mid-sentence would leave
                # a hole a five-year-old reads as a mistake, so the whole answer is
                # replaced by the refusal the card already specifies.
                logger.warning(
                    "figure survived the reprompt at band %s; serving the card's refusal",
                    band,
                )
                text = (
                    "That is something a grown-up should tell you. What I can say "
                    "is that the money is yours, it is safe, and it is growing."
                )

        # ── (b) vocabulary ──────────────────────────────────────────────────
        violations = vocab.check(text, band)
        if violations:
            report["vocab_violations"] = sorted({v.term for v in violations})
            if reprompt is not None:
                timing.note_reprompt("vocab")
                text = await reprompt(vocab.explain(violations, band), text)
                # Re-checked, and a second failure is NOT re-prompted again.
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

            # A rewrite can push the reply back over the cap.
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
            # The model may write its chips as a trailing bulleted list instead of `quick_replies`.
            prose, harvested = parse_chips(text)
            if harvested:
                text = prose
                if not replies:
                    replies = harvested

            if not quick_replies_ok(replies):
                report["quick_replies_missing"] = True
                if reprompt is not None:
                    timing.note_reprompt("chips")
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
                timing.note_reprompt("locale")
                retried = await reprompt(locale_instruction(locale), text)
                # Accepted only if it actually moved.
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

        # Widgets back in.
        if widgets:
            text = original if text == prose_in else sentinel.reattach(text, widgets)

        update: dict[str, Any] = {"safety_flags": flags, "quick_replies": replies}

        # The video offer, last, and here rather than in any one agent: this is
        # where every turn converges, and the client's own example ("what does
        # scarcity mean?") is answered by the tutor rather than by QA. Anything
        # hung off a single agent works for some questions and silently does not
        # for others.
        #
        # It cannot change what was said -- the prose is already capped and
        # stripped above -- and it takes a chip slot rather than adding a fifth,
        # because four is the wire cap and an offer appended fifth is an offer
        # silently dropped.
        from app.videos.offer import offer_for

        offer = offer_for(state, latest_user_text(state))
        if offer is not None:
            video_id, chip = offer
            update["offered_video"] = video_id
            # Remembered for the rest of the conversation, so the same film is
            # never offered twice.
            update["videos_offered"] = [
                *(state.get("videos_offered") or []),
                video_id,
            ]
            update["quick_replies"] = [chip, *replies][:3]
        elif state.get("offered_video") and not flags.get("card"):
            # An offer the reader answered with something else has expired. A
            # "yes" two turns later belongs to whatever was asked in between.
            update["offered_video"] = None

        if text != original:
            # Same message id, so `add_messages` replaces the message instead of appending one.
            update["messages"] = [AIMessage(content=text, id=getattr(last, "id", None))]
        return update

    return safety_out
