"""Choosing a primitive -- or choosing none -- before anything is generated.

Two decisions, split into two model calls, and the split is the whole point.

    plan:     which primitive, if any?   (small model, nine names, no schemas)
    compose:  fill in THAT primitive     (small model, ONE schema, 2-3 examples)

## Why not one call with all nine schemas

Because it costs about 4,000 tokens of schema per turn and it over-triggers. A
model shown nine elaborate options will pick one; shown nine options and told
"or nothing", it still picks one, because nothing is the shortest and least
interesting item on a long list.

Splitting it means the planning call sees nine ONE-LINE descriptions and a
strong instruction to return null, and the composition call sees exactly one
schema and examples of it done well. `test_planner.py` measures both halves --
selection accuracy and over-trigger rate -- because the second is the one that
degrades silently.

## It must return null liberally

A follow-up like "so it's free money?" needs two sentences, not another
simulator. A widget on every turn is wallpaper: the child stops looking at them,
and the one that mattered goes past unnoticed.

`recent_widget_kinds` is passed so the planner avoids the same primitive three
turns running -- variety is not decoration here, it is what keeps a widget
worth looking at.

## It runs in parallel with retrieval

Nothing in the planning input depends on retrieval: it is the message, the
concept, the band and the locale. Starting both together means the widget costs
its own latency and not retrieval's plus its own.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.safety import vocab
from app.widgets.validate import BAND_CONTROL_CAP, BAND_KINDS

logger = logging.getLogger(__name__)

FEWSHOT_DIR = Path(__file__).resolve().parent / "fewshots"

#: One line each, and nine lines total. This is the ENTIRE menu the planning
#: call sees -- no schemas, no field lists.
#:
#: Each line names WHAT IT LOOKS LIKE and then WHEN TO PICK IT, in that order.
#: The first measurement of this prompt ran at 75% with descriptions that only
#: did the first half: the model could tell the primitives apart and could not
#: tell which question each one answered, so `compare`, `reveal_cards` and
#: `sort_buckets` were used interchangeably. The "pick when" clause is what
#: separates them.
KIND_SUMMARIES: dict[str, str] = {
    "simulator": (
        "sliders driving a number -- pick when the answer depends on amounts "
        "the learner should choose for themselves"
    ),
    "growth_stack": (
        "two coin stacks growing year by year -- pick when they ask why money "
        "grows on its own, or what happens if they leave it alone"
    ),
    "compare": (
        "two or three panels that hide their answer until tapped -- pick when "
        "they ask which is better, what the difference is, or why something "
        "happens"
    ),
    "sort_buckets": (
        "things tapped into categories -- pick ONLY when the message names two "
        "groups to tell apart, like needs and wants"
    ),
    "allocator": (
        "a fixed amount split across buckets -- pick when they ask how to "
        "divide or share out money"
    ),
    "flow_diagram": (
        "a short sequence of steps -- pick when they ask where money goes"
    ),
    "timeline": (
        "points along a line -- pick when they ask how long, when, or how much "
        "longer"
    ),
    "reveal_cards": (
        "cards that flip to show a meaning -- pick when they ask what a word "
        "or several words mean"
    ),
    "proportion": (
        "icons with some highlighted -- pick when they ask how much of a whole, "
        "or what share"
    ),
}

#: What the model is asked.
#:
#: Both halves are stated, and in this order. An earlier version led with the
#: null instruction alone and measured 75%: it suppressed the widget on "what is
#: saving", which is the single clearest case for one. The rule is not "usually
#: null" -- it is "null for these shapes of message, a visual for those".
_SYSTEM = """You decide whether a short interactive visual would help a child
understand this message, and if so which kind.

PICK A KIND when the message asks what something IS, how it WORKS, WHY it
happens, HOW LONG, HOW MUCH, or WHICH is better. A child meeting an idea for
the first time is the case a visual is for.

RETURN NULL when the message is:
  - an acknowledgement ("ok", "yes", "thanks", "got it", "cool")
  - fewer than three words
  - a repeat request ("say that again", "what did you say")
  - a follow-up to something you just showed ("so it is free money?")
  - a statement rather than a question ("I want a bike")
  - a request for something else entirely ("can we play a game")

Reply with JSON only:
  {"kind": "<one of the kinds listed, or null>", "rationale": "<eight words>",
   "params_hint": {}}
"""


@dataclass(frozen=True, slots=True)
class Plan:
    """The planner's answer, already checked against the band."""

    kind: str | None
    rationale: str = ""
    params_hint: dict[str, Any] = field(default_factory=dict)
    #: True when the model's choice was overruled -- band, repetition, or an
    #: unknown name. Counted, because the RATE is what says whether the prompt
    #: needs work.
    overruled: bool = False
    #: The concept the widget should be ABOUT, which is not always the concept
    #: that was asked about.
    #:
    #: A nine-year-old asking "what is compound interest?" gets a growth stack
    #: about `interest` -- the concept on their ladder -- rather than about
    #: `compound_interest`, which is not. Without this, gate 3 would reject the
    #: widget the band table just decided they should have.
    concept_id: str = ""
    #: Set when the answer is "not this, but here is what to teach instead".
    #: 5-8 asking about compounding is redirected to saving.
    redirect_to: str | None = None


def kinds_for(age_band: str, concept_id: str, recent: list[str]) -> list[str]:
    """The primitives this planner call may offer.

    Three filters, applied before the model sees anything:

      1. the band's own list (`BAND_KINDS`) -- 5-8 gets no simulator at all;
      2. anything used in the last two turns, so the same primitive does not
         run three turns in a row;
      3. nothing at all if the concept is not on the band's ladder, because a
         widget for a concept they are not being taught is a widget about
         something else.

    Filtering BEFORE the prompt rather than validating after it is what makes
    band violations structurally impossible rather than merely unlikely: gate 3
    is the backstop, and it should never fire.
    """
    if not vocab.is_allowed_concept(concept_id, age_band):
        return []

    permitted = BAND_KINDS.get(age_band, frozenset())
    stale = set(recent[-2:])
    offered = [kind for kind in KIND_SUMMARIES if kind in permitted and kind not in stale]

    # If avoiding repetition emptied the list, allow repeats rather than
    # returning nothing: a repeated primitive beats a lesson with no visual
    # where one genuinely helps.
    return offered or [kind for kind in KIND_SUMMARIES if kind in permitted]


def menu(kinds: list[str]) -> str:
    return "\n".join(f"- {kind}: {KIND_SUMMARIES[kind]}" for kind in kinds)


#: Band adaptation for the one concept the specification names explicitly.
#:
#: A table rather than a prompt instruction, because "which widget does a
#: nine-year-old get for compound interest?" is a product decision with a
#: reviewed answer, and a model asked it fresh each turn gives a different one.
#:
#: 5-8 gets None and the caller redirects to the saving concept: compounding is
#: not on their ladder and no visual makes it so.
COMPOUND_INTEREST_BY_BAND: dict[str, str | None] = {
    "5-8": None,
    "9-12": "growth_stack",
    "13-15": "simulator",
    "16-18": "simulator",
    "adult": "simulator",
}

#: Which concept the widget is actually ABOUT, per band.
#:
#: A nine-year-old asking about compounding gets a widget about `interest`,
#: which is on their ladder; the growth stack teaches the compounding idea
#: without naming it. A six-year-old is redirected to `save` entirely.
COMPOUND_CONCEPT_BY_BAND: dict[str, str] = {
    "5-8": "save",
    "9-12": "interest",
    "13-15": "compound interest",
    "16-18": "compound interest",
    "adult": "compound interest",
}

#: Concept ids that resolve to the compound-interest rule above.
_COMPOUND_ALIASES = frozenset({"compound interest", "interest"})


def forced_kind(concept_id: str, age_band: str) -> tuple[bool, str | None, str]:
    """Whether this concept has a fixed answer, what it is, and what it is about.

    Returns `(True, kind_or_None, concept)` when the decision is made in the
    table above, and `(False, None, "")` when it is the model's to make.
    """
    normalised = concept_id.replace("_", " ").replace("-", " ").strip().lower()
    if normalised in _COMPOUND_ALIASES:
        return (
            True,
            COMPOUND_INTEREST_BY_BAND.get(age_band, "simulator"),
            COMPOUND_CONCEPT_BY_BAND.get(age_band, "compound interest"),
        )
    return False, None, ""


@lru_cache(maxsize=64)
def fewshots(kind: str, age_band: str) -> str:
    """2-3 worked examples for one kind at one band, as prompt text.

    Falls back band-downward, then to any band's examples for that kind, then to
    nothing. Downward first for the same reason the curriculum inherits
    downward: an older reader shown a younger example is fine, and the reverse
    puts words in a prompt that gate 6 will then reject.
    """
    from app.curriculum.schema import BANDS, band_index

    index = band_index(age_band)
    candidates = [BANDS[step] for step in range(index, -1, -1)] if index >= 0 else []
    candidates += [band for band in BANDS if band not in candidates]

    for band in candidates:
        path = FEWSHOT_DIR / f"{kind}_{band}.json"
        if path.exists():
            return _render(json.loads(path.read_text(encoding="utf-8")))
    return ""


@lru_cache(maxsize=1)
def null_examples() -> str:
    """Examples of turns that should NOT get a widget.

    Included in every planning prompt. Showing the model what "no" looks like
    is measurably more effective than telling it that "no" is allowed -- an
    instruction competes with nine attractive options, and an example does not.
    """
    path = FEWSHOT_DIR / "null_any.json"
    if not path.exists():  # pragma: no cover - shipped with the package
        return ""
    rows = json.loads(path.read_text(encoding="utf-8"))
    return "\n".join(
        f'- "{row["question"]}" -> null ({row.get("why", "")})' for row in rows
    )


def _render(rows: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f'Question: {row["question"]}\nWidget:\n'
        + json.dumps(row["widget"], ensure_ascii=False, indent=2)
        for row in rows
        if row.get("widget")
    )


def _parse(raw: str) -> tuple[str | None, str, dict[str, Any]] | None:
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    kind = data.get("kind")
    if isinstance(kind, str) and kind.strip().lower() in ("null", "none", ""):
        kind = None
    hint = data.get("params_hint")
    return (
        kind if isinstance(kind, str) else None,
        str(data.get("rationale") or "")[:80],
        hint if isinstance(hint, dict) else {},
    )


def make_planner(invoke=None):
    """Build the planning call. `invoke` is `async (system, user) -> str`."""

    async def plan_widget(
        *,
        user_message: str,
        concept_id: str,
        age_band: str,
        locale: str = "en",
        recent_widget_kinds: list[str] | None = None,
    ) -> Plan:
        if not get_settings().widgets_enabled:
            return Plan(kind=None, rationale="widgets disabled")

        recent = list(recent_widget_kinds or [])

        # The fixed decisions first, and they are not a model call. A product
        # decision with a reviewed answer must not be re-litigated per turn.
        fixed, kind, about = forced_kind(concept_id, age_band)
        if fixed:
            if kind is None:
                return Plan(
                    kind=None,
                    rationale="not on this band's ladder",
                    redirect_to=about,
                    concept_id=about,
                )
            if kind not in BAND_KINDS.get(age_band, frozenset()):
                # The table and the band list disagree, which is a config bug.
                # Fail towards no widget.
                logger.error(
                    "Forced kind %s for %s is not permitted at that band.", kind, age_band
                )
                return Plan(kind=None, rationale="band conflict", overruled=True)
            return Plan(
                kind=kind, rationale="band rule for this concept", concept_id=about
            )

        offered = kinds_for(age_band, concept_id, recent)
        if not offered:
            return Plan(kind=None, rationale="nothing offered at this band")

        if invoke is None:
            return Plan(kind=None, rationale="no planner configured")

        user = (
            f"Kinds available:\n{menu(offered)}\n\n"
            f"Return null for messages like these:\n{null_examples()}\n\n"
            f"Learner: age band {age_band}, language {locale}.\n"
            f"Concept being taught: {concept_id}.\n"
            f"Recently shown: {', '.join(recent[-3:]) or 'nothing'}.\n\n"
            f"Message: {user_message}"
        )

        try:
            raw = await invoke(_SYSTEM, user)
        except Exception:
            # A planner outage costs a widget, never a turn. Prose is a
            # complete answer on its own.
            logger.warning("Widget planner failed; serving prose.", exc_info=True)
            return Plan(kind=None, rationale="planner unavailable")

        parsed = _parse(raw)
        if parsed is None:
            return Plan(kind=None, rationale="unparseable", overruled=True)

        kind, rationale, hint = parsed
        if kind is None:
            return Plan(kind=None, rationale=rationale)

        if kind not in offered:
            # Overruled rather than coerced to something else. A model that
            # picked a primitive it was not offered has not understood the
            # question, and substituting our own guess would be inventing a
            # lesson.
            logger.info(
                "Planner proposed %r, which is not offered at %s; serving prose.",
                kind[:32],
                age_band,
            )
            return Plan(kind=None, rationale=rationale, overruled=True)

        return Plan(kind=kind, rationale=rationale, params_hint=hint)

    return plan_widget


def composition_prompt(kind: str, age_band: str, locale: str, concept_id: str) -> str:
    """The system prompt for the SECOND call: one schema, a few examples.

    Note what is absent: the other eight schemas. That is the token saving the
    split exists for, and it is also why this call composes better -- a model
    filling in one shape it has seen done well is a much easier task than a
    model choosing a shape and filling it in at once.
    """
    from app.widgets.schemas import model_for

    model = model_for(kind)
    schema = (
        json.dumps(model.model_json_schema(), ensure_ascii=False)
        if model is not None
        else "{}"
    )
    control_cap = BAND_CONTROL_CAP.get(age_band, 0)
    ladder = ", ".join(sorted(vocab.concepts_for(age_band))) or "plain language only"
    banned = ", ".join(sorted(vocab.banned_terms(age_band)))

    return (
        f"Emit ONE {kind} widget as JSON inside ⟦widget⟧ ... ⟦/widget⟧, inline in "
        f"your reply, at the point it helps.\n\n"
        f"Learner: age band {age_band}, language {locale}. Concept: {concept_id}.\n"
        f"Words you may use: {ladder}.\n"
        f"Words you may NOT use: {banned}.\n"
        f"At most {control_cap} control(s).\n"
        "Every label is short. Every widget needs `a11y_text`: the same lesson "
        "in words, for a child using a screen reader.\n"
        "No markup, no links, no colours of your own -- use the colour tokens "
        "in the schema.\n\n"
        f"Schema:\n{schema}\n\n"
        f"Examples:\n{fewshots(kind, age_band)}"
    )
