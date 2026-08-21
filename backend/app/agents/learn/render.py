"""The lesson gets written here, and it is guaranteed to exist."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
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
Nothing after it. The exception is a MOVE that tells you to ask nothing -- follow the
MOVE.

You are teaching a person, not filling a slot. What you say is shaped by what they have
already shown you: build on what they have demonstrated, and do not re-explain from the
beginning something they have just answered correctly.

HOW TO WRITE
- Plain prose. No headings, no markdown, no links, no reference numbers like [ASP-042].
- Warm, and never babyish. You are explaining, not performing.
- Every example is St. Kitts and Nevis and every amount is EC$. Never USD.
- At most one emoji in the whole lesson, and only if the band is 5-8 or 9-12.
- Write only what the learner reads. Never describe what you are doing."""


#: The RAG-teach role.
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
    Move.RETEACH: (
        "MOVE: RETEACH. The way you explained this did not work for them. Do NOT explain "
        "it that way again and do not simply reword it. Follow the DIFFERENT APPROACH "
        "below exactly, then ask the check question."
    ),
    Move.CORRECT_MISCONCEPTION: (
        "MOVE: CORRECT A MISCONCEPTION. They are holding one specific wrong idea, named "
        "below. Do not re-explain the whole concept. Show them the one place their idea "
        "breaks -- ideally with the numbers you were given -- then say what happens "
        "instead, then ask the check question. Address the idea, never the learner: say "
        "what is true, not that they were wrong."
    ),
    Move.ANSWER: (
        "MOVE: ANSWER. They asked for the answer, so give it to them plainly and without "
        "making them work for it further. Then, and this is the part that matters, show "
        "WHY it is that answer, step by step, using the numbers you were given. Ask no "
        "question at the end."
    ),
    Move.GAME: (
        "MOVE: GAME. They have been on this idea for a while and more prose will not "
        "help. In two or three sentences say what the game will ask them to do and why "
        "it is worth a go, then ask them if they want to play it. Do not teach the idea "
        "again and do not ask a check question."
    ),
    Move.STEP_BACK: (
        "MOVE: STEP BACK. What is missing sits underneath this idea, so you are teaching "
        "the earlier idea named below instead. Say in one sentence that you are going to "
        "come at it from further back -- do not say they failed, and do not diagnose them "
        "out loud -- then teach the earlier idea properly and ask its check question."
    ),
}

#: Moves whose prose is not followed by the concept's check question. GAME asks
#: a question of its own ("want to play?"), so it is not silent -- it simply
#: does not end on the bank's item.
_SILENT_MOVES: frozenset[Move] = frozenset({Move.ANSWER})

#: Moves that end on something other than the concept's check question.
_NO_CHECK_QUESTION: frozenset[Move] = frozenset({Move.ANSWER, Move.GAME})


# ── the per-turn context block ───────────────────────────────────────────────


@dataclass(slots=True)
class TeachContext:
    """Everything one teaching call needs, assembled in a fixed order."""

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
    #: What to do differently, from `strategy.instruction_for`, on a RETEACH.
    approach: str = ""
    #: The wrong model to take apart, on a CORRECT_MISCONCEPTION move.
    misconception: str = ""
    #: What is actually true, as the concept's author wrote it.
    correction: str = ""
    #: The answer to give, on an ANSWER move.
    answer: str = ""
    #: What the learner has demonstrated they can already do, so the tutor
    #: neither re-teaches it nor talks down to them.
    demonstrated: tuple[str, ...] = ()

    @property
    def body(self) -> str:
        return (self.concept.body_for(self.band) or "") if self.concept else ""

    def grounding_terms(self) -> tuple[str, ...]:
        """Distinctive words from the concept, for the tier-2 grounding check."""
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
    """The per-turn block, in the fixed order the module docstring names."""
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
            # Named as the ONLY numbers permitted, not as a suggestion.
            numbers = ", ".join(f"{key} = {value}" for key, value in concept.numeric_anchors.items())
            block.append(
                f"\nThe ONLY numbers you may use, exactly as given: {numbers}\n"
                "Do not calculate anything new from them."
            )
        parts.append("\n".join(block))

    if context.supporting:
        # `without_provenance` strips the CSV's bookkeeping columns first. The
        # instruction below says never cite a reference number, and the rows
        # were arriving with `id: ASP-042` and `source_url: https://...` in
        # them -- both of them reference numbers of a kind, one of them a URL.
        from app.sources import without_provenance

        rows = "\n".join(
            f"- {text}"
            for row in context.supporting
            if (text := without_provenance(str(getattr(row, "content", row))))
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
    if context.demonstrated:
        # §7. Level is evidence, not a label applied on the strength of one
        # message, so what is passed here is what they DID.
        state_lines.append(
            "They have answered correctly and unaided on: "
            + ", ".join(context.demonstrated[:6])
            + ". Do not re-explain those from the beginning, and use the proper "
            "terms for them rather than talking around them."
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

    if context.check_item is not None and context.move not in _NO_CHECK_QUESTION:
        parts.append(
            "THE CHECK QUESTION -- ask exactly this, in your own voice, at the very end, "
            f"and nothing after it:\n{context.check_item.question}"
        )
    if context.hint:
        parts.append(f"THE HINT to give, and nothing beyond it:\n{context.hint}")
    if context.verdict:
        parts.append(f"HOW THEIR ANSWER WENT, to say in your own voice:\n{context.verdict}")
    if context.approach:
        parts.append(f"THE DIFFERENT APPROACH to take this time:\n{context.approach}")
    if context.misconception:
        block = f"THE WRONG IDEA they are holding:\n{context.misconception}"
        if context.correction:
            block += f"\n\nWhat is actually true:\n{context.correction}"
        parts.append(block)
    if context.answer:
        parts.append(f"THE ANSWER to give them, and then explain:\n{context.answer}")

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

#: Connectors that stitch a template render into something that reads like a person wrote it.
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
    """The lesson, assembled in Python from the concept row."""
    picker = rng or random.Random()
    phrases = _CONNECTORS.get(band) or _CONNECTORS["9-12"]
    contract = contract_for(band)

    body = concept.body_for(band) or ""
    pieces = [picker.choice(phrases["open"]), body]

    if concept.local_example:
        pieces.append(f"{picker.choice(phrases['example'])} {concept.local_example}")

    # The tail is built separately and kept whole.
    tail = ""
    if check_item is not None:
        tail = f"{picker.choice(phrases['check'])} {check_item.question}".strip()

    text = " ".join(piece.strip() for piece in pieces if piece.strip())
    text = re.sub(r"\s{2,}", " ", text).strip()

    # Trim the explanation to fit the ceiling WITH the question, at a sentence boundary.
    if contract.max_words is not None:
        budget = contract.max_words - word_count(tail)
        if word_count(text) > budget:
            from app.graph.nodes.safety_out import truncate_at_sentence

            if budget >= 20:
                text = truncate_at_sentence(text, budget)

    return f"{text} {tail}".strip() if tail else text


#: ES and FR are MARKED FOR NATIVE-SPEAKER REVIEW before the 20th.
#:
#: This whole function was English, with no locale parameter anywhere in scope,
#: so a Spanish or French child who asked about something the tutor could not
#: resolve was declined in English. Both callers had the locale to hand -- one
#: on `TeachContext`, the other on the graph state -- so the only thing missing
#: was the parameter.
_DECLINE_OPENING: dict[str, dict[str, str]] = {
    "en": {
        "5-8": "I do not know that one yet!",
        "9-12": "That one is not something I have learned yet.",
        "adult": "I do not have anything solid on that one yet, and I would rather say so than guess.",
    },
    "es": {
        "5-8": "¡Esa todavía no me la sé!",
        "9-12": "Esa aún no la he aprendido.",
        "adult": "Sobre eso todavía no tengo nada firme, y prefiero decirlo antes que adivinar.",
    },
    "fr": {
        "5-8": "Celle-là, je ne la sais pas encore !",
        "9-12": "Celle-là, je ne l'ai pas encore apprise.",
        "adult": "Je n'ai rien de solide là-dessus pour l'instant, et je préfère le dire plutôt que deviner.",
    },
}

#: The offer around the concept titles. The titles themselves stay in the
#: corpus's own language, exactly as `escalation/decline.py` already does it:
#: the frame is localised, the topic is quoted.
_DECLINE_OFFER: dict[str, dict[str, str]] = {
    "en": {
        "two": "{opening} I could teach you about {first}, or about {second}. Which sounds better?",
        "one": "{opening} I could teach you about {first} instead. Shall we?",
        "none": "{opening} Ask me something else about money and I will see what I have.",
    },
    "es": {
        "two": "{opening} Puedo enseñarte sobre {first}, o sobre {second}. ¿Cuál prefieres?",
        "one": "{opening} Puedo enseñarte sobre {first}. ¿Empezamos?",
        "none": "{opening} Pregúntame otra cosa sobre el dinero y veré qué tengo.",
    },
    "fr": {
        "two": "{opening} Je peux t'expliquer {first}, ou {second}. Lequel préfères-tu ?",
        "one": "{opening} Je peux t'expliquer {first} à la place. On commence ?",
        "none": "{opening} Pose-moi une autre question sur l'argent et je verrai ce que j'ai.",
    },
}


def decline_text(
    band: str, alternatives: Sequence[TeachingConcept], locale: str = "en"
) -> str:
    """What to say when nothing was resolved."""
    speech = _DECLINE_OPENING.get(locale, _DECLINE_OPENING["en"])
    offer = _DECLINE_OFFER.get(locale, _DECLINE_OFFER["en"])
    opening = speech.get(band, speech["adult"])

    offers = [concept.title.lower() for concept in alternatives[:2]]
    if len(offers) >= 2:
        return offer["two"].format(opening=opening, first=offers[0], second=offers[1])
    if offers:
        return offer["one"].format(opening=opening, first=offers[0])
    return offer["none"].format(opening=opening)


# ── the three-tier renderer ──────────────────────────────────────────────────


@dataclass(slots=True)
class RenderResult:
    """The lesson, and how it was arrived at."""

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
    """Write the lesson."""
    role = LEARN_ROLE if context.concept is not None else RAG_TEACH_ROLE
    turn_block = build_teach_context(context)
    expect_question = context.move not in _SILENT_MOVES and (
        context.move is not Move.HINT or context.check_item is not None
    )
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
    # `servable`, not `ok`.
    if text and result.servable:
        if result.violations:
            logger.info(
                "Serving a lesson with advisory violations: %s",
                [violation.code for violation in result.violations],
            )
        return _finish(RenderResult(text=text, tier=1, contract=result), context)

    if text:
        logger.info(
            "Lesson failed the %s contract (%d words); retrying. Violations: %s",
            context.band,
            result.words,
            [violation.code for violation in result.blocking],
        )

    # ── tier 2: one retry, with the violation quoted ────────────────────────
    if invoke is not None:
        # Every violation is quoted, not only blocking ones: the model is rewriting anyway.
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
        if retried and second.servable:
            return _finish(RenderResult(text=retried, tier=1, retry=True, contract=second), context)

        # An imperfect retry still beats the template, unless it came out far too short.
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
            context.concept,
            band=context.band,
            # A move that asks nothing gets no question, even from the floor.
            check_item=None if context.move in _NO_CHECK_QUESTION else context.check_item,
            rng=rng,
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
    logger.warning(
        "teach_fallback=decline band=%s move=%s: nothing to teach from.",
        context.band,
        context.move.value,
    )
    return _finish(
        RenderResult(text=decline_text(context.band, (), context.locale), tier=3), context
    )


def _finish(result: RenderResult, context: TeachContext) -> RenderResult:
    """Attach the spoken rendering. One lesson, two channels."""
    result.spoken = tts_safe(result.text) if context.voice else result.text
    return result


def _default_user_turn(context: TeachContext) -> str:
    """What to put in the human turn when the learner said nothing."""
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
    """One model call, or None."""
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
        # No resolved session context: a unit test, or a turn where resolution did not run.
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
