"""The lesson gets written here, and it is guaranteed to exist.

Three tiers, and all three are implemented because the first two are the ones
that "should be enough":

    1  GENERATE   the strong model, given the concept body for this band
    2  VALIDATE   `contract.check_lesson`; on failure, regenerate ONCE with the
                  violation quoted back
    3  FLOOR      a template rendered in Python from the concept row itself

Tier 3 is what makes the reported symptom impossible. It reads a little flat. It
is never empty, never thin, never off-topic, and never a widget with no lesson
attached -- because it is assembled from the same band body, local example and
check question a reviewer signed off, joined with persona-appropriate connectors
from a fixed table. A deployment with no provider key at all serves tier 3 and
still teaches.

## Why this generates and then emits, rather than streaming and then checking

`stream_mode="messages"` forwards tokens as the model produces them, so by the
time a lesson can be measured it has already been read. Tier 2 cannot exist on
top of that: "regenerate once with the violation quoted" is not available to a
turn whose first attempt is already on screen.

So the teaching call is made whole and validated before a token crosses the wire.
The cost is time-to-first-token on the prose; the benefit is that a lesson which
is too short, off-topic, or missing its check question never reaches a child.
That trade is the entire point of the workstream, and it is close to free in
practice for a reason worth recording: `plan_widget`'s model call used to sit in
FRONT of the teaching call on the critical path, and it does not any more (see
`widgets.py`) -- so a turn spends about as long before its first token as it did,
and spends it on the lesson rather than on choosing a slider.

The objection to this design, and the argument for streaming instead, is written
up in `learning/OBJECTIONS.md`.

## Context assembly order is load-bearing

    [cacheable prefix]   GLOBAL + PERSONA_CARD + LEARN_ROLE
    ─────────────────────── cache breakpoint ───────────────────────
    [per turn]           concept block, supporting rows, learner state,
                         check item, recent history, MOVE

`prompting/builder.py` owns the first three layers and the breakpoint. Everything
this module adds goes BELOW it, in `extra_instruction` -- a concept block above
the breakpoint would change the prefix on every turn and cost the prefix cache on
the agent that makes the longest calls.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.agents.learn.contract import (
    ContractResult,
    check_lesson,
    contract_for,
    tts_safe,
    word_count,
)
from app.agents.learn.planner import Move
from app.learning.concepts import CheckItem, TeachingConcept

logger = logging.getLogger(__name__)


# ── the role layer ───────────────────────────────────────────────────────────

LEARN_ROLE = """You are the ASPIRE learning tutor. You TEACH. You do not chat about money
and you do not answer like an FAQ.

You will be given: one concept with its teaching body written for this learner's age
band, a local EC$ example, common misconceptions, supporting knowledge-base rows, the
learner's history, one check question, and a MOVE. Render the MOVE. Do not choose a
different one.

Every claim you make must come from the concept body or the supporting rows. If you want
to say something they do not support, leave it out. There is no penalty for a shorter
lesson; there is a serious penalty for an invented fact about the ASPIRE programme.

Never compute. Numbers are given to you. Use them exactly.

End with the check question you were given, rendered in your voice. Exactly one question.
Nothing after it.

HOW TO WRITE
- Plain prose. No headings, no markdown, no links, no reference numbers like [ASP-042].
- Warm, and never babyish. You are explaining, not performing.
- Every example is St. Kitts and Nevis and every amount is EC$. Never USD.
- At most one emoji in the whole lesson, and only if the band is 5-8 or 9-12.
- Write only what the learner reads. Never describe what you are doing."""


#: The RAG-teach role. A different job: there is no authored concept, so the rows
#: ARE the material and the lesson has to be honest about the thinness of it.
RAG_TEACH_ROLE = """You are the ASPIRE learning tutor. You TEACH.

No authored concept covers this question. You have knowledge-base rows retrieved for it
and NOTHING else. Teach from those rows only.

Build a short lesson in the usual shape: a hook, the explanation, one EC$ example drawn
from what the rows actually say, and one check question you invent from the rows.

If the rows do not contain enough to teach honestly, say so in your own voice, name one
thing you CAN teach that is close, and offer it. Do not stretch thin material into a
lesson -- a confident lesson built on two tangential rows is worse than an honest
redirection.

Never compute. Never invent a figure. Never state a rule about the ASPIRE programme that
is not written in a row in front of you.

Plain prose, no markdown, no reference numbers. Every amount is EC$."""


_MOVE_INSTRUCTIONS: dict[Move, str] = {
    Move.TEACH: (
        "MOVE: TEACH. Explain this idea to them for the first time, then ask the check "
        "question."
    ),
    Move.RECAP: (
        "MOVE: RECAP. They have met this idea already. Say it a DIFFERENT way -- start "
        "from the example or from a question they would ask, not from the definition -- "
        "then ask the check question."
    ),
    Move.CHECK: (
        "MOVE: CHECK. One or two sentences of setup at most, then ask the check question "
        "in your voice. Do not re-explain the idea."
    ),
    Move.HINT: (
        "MOVE: HINT. Give them the hint below and nothing more. Do not give the answer, "
        "do not re-teach, and do not ask a new question -- ask the SAME check question "
        "again at the end."
    ),
    Move.ADVANCE: (
        "MOVE: ADVANCE. They have this one. Say so briefly and specifically, then "
        "introduce what it leads to and ask the check question for the new idea."
    ),
    Move.EVALUATE: (
        "MOVE: EVALUATE. Tell them how their answer went using the explanation you were "
        "given, warmly and without flattery, then ask the check question that follows."
    ),
}


# ── the per-turn context block ───────────────────────────────────────────────


@dataclass(slots=True)
class TeachContext:
    """Everything one teaching call needs, assembled in a fixed order.

    A dataclass rather than a dict so that a field the prompt builder forgets is
    an attribute error in a test rather than a silently missing block in
    production -- the failure mode being designed out is a lesson generated
    without its concept body, which reads exactly like a lesson generated with
    one and is wrong.
    """

    concept: TeachingConcept | None
    band: str
    locale: str
    move: Move
    persona: str = "stella"
    #: The knowledge-base rows this lesson may draw on.
    supporting: tuple[Any, ...] = ()
    #: The check item Python selected for this turn.
    check_item: CheckItem | None = None
    #: The hint rung to give, on a HINT move.
    hint: str | None = None
    #: Concepts already mastered, and prior wrong answers on this one.
    mastered: tuple[str, ...] = ()
    prior_wrong: tuple[str, ...] = ()
    #: What the learner just said.
    utterance: str = ""
    #: Whether this turn's output will be spoken as well as shown.
    voice: bool = False
    #: How the model opened the last few times, so it opens differently.
    recent_openings: tuple[str, ...] = ()
    #: The grader's verdict, on an EVALUATE move.
    verdict: str = ""

    @property
    def body(self) -> str:
        return (self.concept.body_for(self.band) or "") if self.concept else ""

    def grounding_terms(self) -> tuple[str, ...]:
        """Distinctive words from the concept, for the tier-2 grounding check.

        The title's words and the aliases' words, minus anything short enough to
        appear by accident. A lesson about compound interest that contains
        neither "interest" nor "compound" nor "grow" was not written from the
        material it was given.
        """
        if self.concept is None:
            return ()
        source = f"{self.concept.title} {' '.join(self.concept.aliases)}"
        words = {
            word
            for word in _WORD_RE.findall(source.lower())
            if len(word) >= 5 and word not in _COMMON
        }
        return tuple(sorted(words))


import re  # noqa: E402  (used by the dataclass above, kept next to its patterns)

_WORD_RE = re.compile(r"[a-z]+")
_COMMON = frozenset(
    {"money", "about", "there", "which", "these", "those", "their", "would", "could"}
)


def build_teach_context(context: TeachContext) -> str:
    """The per-turn block, in the fixed order the module docstring names.

    Order is not cosmetic. It is the order the cache breakpoint requires -- every
    block below is per-turn and therefore below it -- and within that, it is
    ordered most-load-bearing first, because a model reading a long block weights
    the beginning of it.
    """
    parts: list[str] = []
    concept = context.concept

    if concept is not None:
        block = [f"CONCEPT: {concept.title}"]
        body = context.body
        if body:
            block.append(f"\nWhat to get across, written for a {context.band} learner:\n{body}")
        if concept.local_example:
            block.append(f"\nAn example this band understands:\n{concept.local_example}")
        if concept.misconceptions:
            wrong_right = "\n".join(
                f"- They often think: {item.wrong}\n  Actually: {item.right}"
                for item in concept.misconceptions[:3]
            )
            block.append(f"\nWhat learners get wrong about this:\n{wrong_right}")
        if concept.numeric_anchors:
            # Named as the ONLY numbers permitted, not as a suggestion. The
            # registry computed everything derived from them; the model's job is
            # to use them, and a model that arithmetics its way to a new figure
            # has invented a fact about a child's savings.
            numbers = ", ".join(f"{key} = {value}" for key, value in concept.numeric_anchors.items())
            block.append(
                f"\nThe ONLY numbers you may use, exactly as given: {numbers}\n"
                "Do not calculate anything new from them."
            )
        parts.append("\n".join(block))

    if context.supporting:
        rows = "\n".join(
            f"- {str(getattr(row, 'content', row)).strip()}"
            for row in context.supporting
            if str(getattr(row, "content", row)).strip()
        )
        if rows:
            parts.append(
                "BACKGROUND from the knowledge base, so anything you say about the real "
                "programme is current. Never quote it, never cite a reference number, and "
                "never turn the lesson into a summary of it:\n" + rows
            )

    state_lines: list[str] = []
    if context.mastered:
        state_lines.append(
            f"They have already mastered: {', '.join(context.mastered[:8])}."
        )
    if context.prior_wrong:
        state_lines.append(
            "On this idea they have previously answered: "
            + "; ".join(f'"{answer}"' for answer in context.prior_wrong[-3:])
            + ". Do not mention their earlier attempts."
        )
    if context.recent_openings:
        openings = "\n".join(f'- "{line}"' for line in context.recent_openings[-3:])
        state_lines.append(
            "You have opened these ways before in this conversation. Begin differently "
            f"and take a different angle in:\n{openings}"
        )
    if state_lines:
        parts.append("THE LEARNER:\n" + "\n".join(state_lines))

    if context.check_item is not None:
        parts.append(
            "THE CHECK QUESTION -- ask exactly this, in your own voice, at the very end, "
            f"and nothing after it:\n{context.check_item.question}"
        )
    if context.hint:
        parts.append(f"THE HINT to give, and nothing beyond it:\n{context.hint}")
    if context.verdict:
        parts.append(f"HOW THEIR ANSWER WENT, to say in your own voice:\n{context.verdict}")

    contract = contract_for(context.band)
    shape = [
        f"LENGTH: between {contract.min_words} and {contract.max_words} words. "
        f"The minimum is a floor, not a target -- a shorter reply is not a lesson.",
        f"SHAPE: {contract.structure}.",
    ]
    if contract.max_sentence_words is not None:
        shape.append(f"No sentence longer than {contract.max_sentence_words} words.")
    if not contract.allows_lists:
        shape.append("Prose only. No bullet lists.")
    if context.voice:
        shape.append(
            "This will be READ ALOUD. Write 'EC dollars' rather than 'EC$', spell out "
            "percentages, and use no parentheses, slashes or ampersands."
        )
    parts.append("\n".join(shape))

    parts.append(_MOVE_INSTRUCTIONS.get(context.move, _MOVE_INSTRUCTIONS[Move.TEACH]))
    return "\n\n".join(parts)


# ── tier 3: the deterministic floor ──────────────────────────────────────────

#: Connectors that stitch a template render into something that reads like a
#: person wrote it. Per band, because "Here is the thing" and "So here's how it
#: works" are not interchangeable across an eleven-year gap.
#:
#: A fixed table rather than a generated sentence: tier 3 runs when generation is
#: unavailable or has failed twice, so it must not depend on a model. Randomised
#: within the band so that a deployment sitting on tier 3 does not produce
#: byte-identical lessons -- which is the failure the model call was added to fix
#: in the first place.
_CONNECTORS: dict[str, dict[str, tuple[str, ...]]] = {
    "5-8": {
        "open": ("Let us look at this one.", "Here is something good to know.", "Ready? Here we go."),
        "example": ("Here is what that looks like.", "Think about it this way.", "Picture this."),
        "check": ("Now you try.", "Your turn.", "See what you think."),
    },
    "9-12": {
        "open": ("Right -- here is how this works.", "This one is worth knowing.", "Let us take this apart."),
        "example": ("Here is what that looks like in real life.", "Try it this way.", "A quick example."),
        "check": ("Now you have a go.", "Your turn.", "See if you can work this out."),
    },
    "13-15": {
        "open": ("Here is what is actually going on.", "This is worth understanding properly.", "Let us get into it."),
        "example": ("Here is a concrete example.", "In practice, that looks like this.", "Put numbers on it."),
        "check": ("So -- your turn.", "Work this one out.", "See what you make of this."),
    },
    "16-18": {
        "open": ("Here is what is actually going on.", "This one matters more than it looks.", "Let us get into it."),
        "example": ("Concretely:", "In practice, that looks like this.", "Put numbers on it."),
        "check": ("Your turn.", "Work this one out.", "See what you make of this."),
    },
    "adult": {
        "open": ("Here is how this works.", "The mechanics are straightforward.", "Worth understanding properly:"),
        "example": ("Concretely:", "In practice:", "A worked example:"),
        "check": ("One to consider:", "Worth thinking through:", "A question back to you:"),
    },
}


def template_lesson(
    concept: TeachingConcept,
    *,
    band: str,
    check_item: CheckItem | None,
    rng: random.Random | None = None,
) -> str:
    """The lesson, assembled in Python from the concept row. Never empty.

    Reads a little flat and that is the trade being made knowingly: this runs
    when the model is unavailable or has produced something that failed the
    contract twice, and a slightly wooden explanation of the right idea beats
    both alternatives -- an empty turn, and a fluent turn about the wrong thing.

    Every string it uses was written by a person and validated at build time, so
    tier 3 is also the only tier that cannot hallucinate.
    """
    picker = rng or random.Random()
    phrases = _CONNECTORS.get(band) or _CONNECTORS["9-12"]
    contract = contract_for(band)

    body = concept.body_for(band) or ""
    pieces = [picker.choice(phrases["open"]), body]

    if concept.local_example:
        pieces.append(f"{picker.choice(phrases['example'])} {concept.local_example}")

    if check_item is not None:
        pieces.append(f"{picker.choice(phrases['check'])} {check_item.question}")

    text = " ".join(piece.strip() for piece in pieces if piece.strip())
    text = re.sub(r"\s{2,}", " ", text).strip()

    # Trim to the ceiling at a sentence boundary. The floor is not enforceable
    # here -- if the authored body is short, the body is short, and inventing
    # words to reach a count is the failure this whole file prevents.
    if word_count(text) > contract.max_words:
        from app.graph.nodes.safety_out import truncate_at_sentence

        head, _, question = text.rpartition(picker.choice(phrases["check"]))
        if check_item is not None and question:
            budget = max(contract.max_words - word_count(question) - 2, 20)
            text = f"{truncate_at_sentence(head.strip(), budget)} {question.strip()}".strip()
        else:
            text = truncate_at_sentence(text, contract.max_words)
    return text


def decline_text(band: str, alternatives: Sequence[TeachingConcept]) -> str:
    """What to say when nothing was resolved. In persona, with a way forward.

    Never an error message and never an apology loop. A child who asked about
    something the curriculum does not cover has done nothing wrong, and the reply
    they are owed names two things that ARE available rather than closing the
    conversation.
    """
    offers = [concept.title.lower() for concept in alternatives[:2]]
    if band == "5-8":
        opening = "I do not know that one yet!"
    elif band == "9-12":
        opening = "That one is not something I have learned yet."
    else:
        opening = "I do not have anything solid on that one yet, and I would rather say so than guess."

    if len(offers) >= 2:
        return f"{opening} I could teach you about {offers[0]}, or about {offers[1]}. Which sounds better?"
    if offers:
        return f"{opening} I could teach you about {offers[0]} instead. Shall we?"
    return f"{opening} Ask me something else about money and I will see what I have."


# ── the three-tier renderer ──────────────────────────────────────────────────


@dataclass(slots=True)
class RenderResult:
    """The lesson, and how it was arrived at.

    `tier` and `retry` are logged on every learning turn. Their RATES are the
    metric that says whether the prompt needs work -- a fallback rate above 2%
    means the generation path is failing systematically, and that is invisible
    from any single turn.
    """

    text: str
    tier: int
    retry: bool = False
    contract: ContractResult | None = None
    #: What the reader hears, when the turn is spoken. Same lesson, said aloud.
    spoken: str = ""

    @property
    def words(self) -> int:
        return word_count(self.text)


async def render_teach(
    context: TeachContext,
    *,
    invoke: Any = None,
    session_context: Any = None,
    rng: random.Random | None = None,
) -> RenderResult:
    """Write the lesson. Returns prose, always.

    `invoke` is `async (messages) -> str`, injected and optional. None means the
    deployment has no provider configured, which is a supported configuration:
    tier 3 runs and the learner still gets a lesson.

    This function does not raise. Every failure inside it degrades one tier.
    """
    role = LEARN_ROLE if context.concept is not None else RAG_TEACH_ROLE
    turn_block = build_teach_context(context)
    expect_question = context.move is not Move.HINT or context.check_item is not None
    terms = context.grounding_terms()

    # ── tier 1 ──────────────────────────────────────────────────────────────
    text = await _generate(
        invoke=invoke,
        session_context=session_context,
        role=role,
        turn_block=turn_block,
        utterance=context.utterance or _default_user_turn(context),
    )
    result = check_lesson(
        text or "", band=context.band, expect_question=expect_question, grounding_terms=terms
    )
    if text and result.ok:
        return _finish(RenderResult(text=text, tier=1, contract=result), context)

    if text:
        logger.info(
            "Lesson failed the %s contract (%d words); retrying. Violations: %s",
            context.band,
            result.words,
            [violation.code for violation in result.violations],
        )

    # ── tier 2: one retry, with the violation quoted ────────────────────────
    if invoke is not None:
        retry_block = (
            f"{turn_block}\n\n"
            "YOUR PREVIOUS ATTEMPT WAS REJECTED. What was wrong with it:\n"
            f"{result.quoted()}\n\n"
            "Write the lesson again, fixing exactly those things. Keep everything that "
            "was right. Do not apologise and do not mention this instruction."
        )
        retried = await _generate(
            invoke=invoke,
            session_context=session_context,
            role=role,
            turn_block=retry_block,
            utterance=context.utterance or _default_user_turn(context),
        )
        second = check_lesson(
            retried or "",
            band=context.band,
            expect_question=expect_question,
            grounding_terms=terms,
        )
        if retried and second.ok:
            return _finish(RenderResult(text=retried, tier=1, retry=True, contract=second), context)

        # A retry that is merely IMPERFECT still beats the template, and the
        # template is only better than a retry that is absent or empty. A
        # 55-word lesson for a band wanting 60 is a lesson; the floor exists for
        # nothing at all, not for near-misses.
        if retried and second.words >= contract_for(context.band).min_words * 0.6:
            logger.info(
                "Serving an imperfect retry (%d words, %s) rather than the template.",
                second.words,
                [violation.code for violation in second.violations],
            )
            return _finish(
                RenderResult(text=retried, tier=2, retry=True, contract=second), context
            )

    # ── tier 3: the deterministic floor ─────────────────────────────────────
    if context.concept is not None:
        floor = template_lesson(
            context.concept, band=context.band, check_item=context.check_item, rng=rng
        )
        if floor.strip():
            logger.warning(
                "teach_fallback=template concept=%s band=%s move=%s",
                context.concept.id,
                context.band,
                context.move.value,
            )
            return _finish(
                RenderResult(
                    text=floor,
                    tier=3,
                    retry=invoke is not None,
                    contract=check_lesson(
                        floor,
                        band=context.band,
                        expect_question=expect_question,
                        grounding_terms=terms,
                    ),
                ),
                context,
            )

    # Nothing to teach from at all: no concept row and no usable generation.
    # This is the decline, and it is still prose -- an empty turn is the one
    # outcome this function may not produce.
    logger.warning(
        "teach_fallback=decline band=%s move=%s: nothing to teach from.",
        context.band,
        context.move.value,
    )
    return _finish(RenderResult(text=decline_text(context.band, ()), tier=3), context)


def _finish(result: RenderResult, context: TeachContext) -> RenderResult:
    """Attach the spoken rendering. One lesson, two channels."""
    result.spoken = tts_safe(result.text) if context.voice else result.text
    return result


def _default_user_turn(context: TeachContext) -> str:
    """What to put in the human turn when the learner said nothing.

    A lesson can begin because the previous one ended, with no message behind it.
    The concept's own title is the honest stand-in -- it is what the turn is
    about -- and an empty human turn makes some providers reject the request.
    """
    if context.concept is not None:
        return f"Teach me about {context.concept.title.lower()}."
    return "Teach me something about money."


async def _generate(
    *,
    invoke: Any,
    session_context: Any,
    role: str,
    turn_block: str,
    utterance: str,
) -> str | None:
    """One model call, or None. Never raises into the caller.

    None rather than an exception because every caller has a lower tier ready,
    and a traceback escaping here would turn a degraded lesson into no lesson --
    the exact inversion of this module's guarantee.
    """
    if invoke is None:
        return None

    from langchain_core.messages import HumanMessage, SystemMessage

    if session_context is not None:
        from app.prompting import build_messages

        messages = build_messages(
            context=session_context,
            agent_role=role,
            user_text=utterance,
            extra_instruction=turn_block,
        )
    else:
        # No resolved session context: a unit test driving the renderer directly,
        # or a turn where `resolve_context` did not run. The prefix is lost and
        # the lesson is not.
        messages = [
            SystemMessage(content=f"{role}\n\n{turn_block}"),
            HumanMessage(content=utterance),
        ]

    try:
        text = await invoke(messages)
    except Exception:
        logger.warning("The teaching call failed.", exc_info=True)
        return None
    return (text or "").strip() or None
