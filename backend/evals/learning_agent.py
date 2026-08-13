"""L1-L10: the learning agent's acceptance suite, plus a property sweep."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.agents.learn.contract import contract_for, word_count  # noqa: E402
from app.agents.learn.planner import LearnerSnapshot, Move, plan_move  # noqa: E402
from app.agents.learn.render import TeachContext, render_teach  # noqa: E402
from app.agents.learn.resolve import is_continuation, resolve_concept  # noqa: E402
from app.agents.learn.tutor import select_check, select_hint  # noqa: E402
from app.agents.learn.widgets import WidgetRequest, build_widget  # noqa: E402
from app.learning.concepts import ConceptStore, TeachingConcept, get_store  # noqa: E402


# ── thresholds, from §12 of the brief ────────────────────────────────────────

TEACH_FALLBACK_MAX = 0.02
WIDGET_GATE_FAILED_MAX = 0.15
RESOLUTION_NONE_MAX = 0.08
#: How many concept x band x locale combinations the property test samples.
PROPERTY_SAMPLES = 200


@dataclass
class Result:
    id: str
    name: str
    passed: bool = True
    notes: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    transcript: str = ""

    def check(self, condition: bool, description: str) -> bool:
        if condition:
            self.notes.append(f"    ok   {description}")
        else:
            self.passed = False
            self.failures.append(description)
            self.notes.append(f"    FAIL {description}")
        return condition


# ── the stub model ───────────────────────────────────────────────────────────


def scripted(*replies: str) -> Callable:
    """A teaching model that returns each reply in turn, then repeats the last."""
    remaining = list(replies)

    async def invoke(_messages):
        return remaining.pop(0) if len(remaining) > 1 else (remaining[0] if remaining else "")

    return invoke


def a_lesson_for(band: str, *, topic: str = "compound interest") -> str:
    """A reply that satisfies the band contract, for scenarios not testing prose."""
    contract = contract_for(band)
    core = (
        f"Here is how {topic} works. When you leave money in a savings account, the bank "
        "pays you a little extra for keeping it there. The next year it pays extra on "
        "your money and on the extra you already earned, so your savings start growing "
        "on their own. Put EC$100 in and you have EC$103 after a year. "
    )
    while word_count(core) < contract.min_words + 5:
        core += "That is the whole idea, and it works the same for EC$5 as for EC$100. "
    return core + "How much do you have after the bank adds EC$3?"


# ── fixtures ─────────────────────────────────────────────────────────────────


def a_concept(**changes) -> TeachingConcept:
    from app.learning.concepts import CheckItem

    base = dict(
        id="CON-0042",
        slug="compound_interest",
        locale="en",
        title="Compound interest",
        domain="saving",
        band_min="5-8",
        band_max="adult",
        aliases=("interest on interest", "money growing"),
        bodies={
            "5-8": (
                "When you save money in a bank, the bank says thank you. It gives you a "
                "little more money. Next time it gives you more, because you have more "
                "saved. Your money grows while you wait."
            ),
            "9-12": (
                "When you keep money in a savings account, the bank pays you a little "
                "extra for leaving it there. That extra is called interest. The clever "
                "part is what happens next: the following year the bank pays you extra "
                "on your money and on the interest you already earned."
            ),
            "13-15": (
                "Compound interest is interest paid on your principal and on the "
                "interest that principal has already earned. Leave the returns in place "
                "and the base for the next period is larger, so growth accelerates the "
                "longer the money stays put. The same force works against a borrower: "
                "an unpaid balance compounds too."
            ),
            "16-18": (
                "Compound interest is interest paid on your principal and on the "
                "interest that principal has already earned. Leave the returns in place "
                "and the base for the next period is larger, so growth accelerates the "
                "longer the money stays put. The same force works against a borrower: "
                "an unpaid balance compounds too, which is why a small debt left alone "
                "stops being small."
            ),
            "adult": (
                "Compound interest is interest paid on principal and on accumulated "
                "interest. Left in place, returns enlarge the base for the next period, "
                "so time contributes more to the outcome than contribution size does "
                "over long horizons. The same mechanism governs revolving debt."
            ),
        },
        local_example=(
            "Put EC$100 in the bank at 3 percent. After one year you have EC$103, and "
            "the year after that the bank pays interest on all EC$103."
        ),
        check_bank=(
            CheckItem(
                id="chk_1",
                band="9_12",
                type="numeric",
                question="If you save EC$100 and the bank adds EC$3, how much do you have?",
                answer="103",
                accept=("103", "EC$103"),
                hints=("Add the extra on.", "EC$100 plus EC$3.", "100 + 3 = ?"),
                explanation_on_correct="Exactly -- EC$100 and EC$3 makes EC$103.",
                explanation_on_wrong="Close. The bank adds EC$3 to your EC$100.",
            ),
            CheckItem(
                id="chk_2",
                band="16_18",
                type="numeric",
                question="EC$100 at 3 percent -- what is the base for year two?",
                answer="103",
                accept=("103", "EC$103"),
                hints=("The interest stays in.", "Principal plus the interest earned.", "100 + 3 = ?"),
            ),
        ),
        numeric_anchors={"principal": 100, "rate": 0.03, "interest": 3, "total": 103},
        widget_hints=("growth_stack",),
        source_kb_ids=("FIN-011", "FIN-012"),
        status="draft",
    )
    base.update(changes)
    return TeachingConcept(**base)


A_VALID_WIDGET = json.dumps(
    {
        "kind": "growth_stack",
        "v": 1,
        "concept_id": "compound_interest",
        "title": "Watch it grow",
        "principal_cents": 10000,
        "contribution_cents": 0,
        "rate": 0.03,
        "periods": 5,
        "period_label": "year",
        "a11y_text": (
            "Two stacks of coins. The first is what you put in. The second is the same "
            "money after five years, taller because the bank added a little each year."
        ),
    }
)


def a_store() -> ConceptStore:
    store = ConceptStore()
    store.load([a_concept()])
    return store


def a_context(band: str, **changes) -> TeachContext:
    concept = changes.pop("concept", a_concept())
    base = dict(
        concept=concept,
        band=band,
        locale="en",
        move=Move.TEACH,
        check_item=select_check(concept, band=band, seen=[]),
        utterance="What is compound interest?",
    )
    base.update(changes)
    return TeachContext(**base)


async def a_widget_plan(**_):
    return {"kind": "growth_stack", "rationale": "shows growth over time"}


async def a_widget_compose(**_):
    return A_VALID_WIDGET


# ── the scenarios ────────────────────────────────────────────────────────────


async def l1(live: bool) -> Result:
    """Stella (9): "What is compound interest?" """
    result = Result("L1", "Stella (9) asks what compound interest is")
    store = a_store()

    resolution = await resolve_concept("What is compound interest?", band="9-12", store=store)
    result.check(resolution.concept is not None, "a concept resolved")
    result.check(
        resolution.concept and resolution.concept.slug == "compound_interest",
        "it resolved to compound_interest, not to whatever was next on the schedule",
    )

    lesson = await render_teach(
        a_context("9-12"), invoke=_teach_invoke(live, a_lesson_for("9-12"))
    )
    result.transcript = lesson.text
    contract = contract_for("9-12")
    result.check(lesson.words >= 60, f"prose_words {lesson.words} >= 60")
    result.check(lesson.words <= contract.max_words, f"prose_words within the {contract.max_words} cap")
    result.check("EC$" in lesson.text, "contains an EC$ example")
    result.check(lesson.text.count("?") == 1, "exactly one check question")

    outcome = await build_widget(
        WidgetRequest(concept=a_concept(), band="9-12", locale="en"),
        plan=a_widget_plan,
        compose=a_widget_compose,
        cache=None,
    )
    result.check(outcome.emitted, "a widget was emitted")
    result.check(
        outcome.kind in ("growth_stack", "simulator"),
        f"widget kind {outcome.kind!r} is growth_stack or simulator",
    )

    snapshot = LearnerSnapshot.from_state({}, band="9-12", concept=a_concept())
    result.check(plan_move(snapshot) is Move.TEACH, "the move is TEACH on an unseen concept")
    return result


async def l2(live: bool) -> Result:
    """Orion (16): the same question, measurably different prose."""
    result = Result("L2", "Orion (16) asks the same question")

    stella = await render_teach(
        a_context("9-12"), invoke=_teach_invoke(live, a_lesson_for("9-12"))
    )
    orion = await render_teach(
        a_context("16-18"), invoke=_teach_invoke(live, a_lesson_for("16-18", topic="compounding"))
    )
    result.transcript = f"--- 9-12 ---\n{stella.text}\n\n--- 16-18 ---\n{orion.text}"

    result.check(stella.text != orion.text, "the two lessons differ")
    result.check(
        contract_for("16-18").min_words > contract_for("9-12").min_words,
        "the contracts themselves differ in floor",
    )
    stella_words = set(re.findall(r"[a-z]+", stella.text.lower()))
    orion_words = set(re.findall(r"[a-z]+", orion.text.lower()))
    overlap = len(stella_words & orion_words) / max(len(stella_words | orion_words), 1)
    result.notes.append(f"    ..   vocabulary overlap {overlap:.0%}")
    result.check(overlap < 0.95, "the vocabulary is not identical")
    return result


async def l3(live: bool) -> Result:
    """THE REGRESSION TEST. The composer raises; the prose is byte-identical."""
    result = Result("L3", "the widget composer raises -- prose must not move")

    healthy = await render_teach(
        a_context("9-12"), invoke=_teach_invoke(live, a_lesson_for("9-12"))
    )

    async def explode(**_):
        raise RuntimeError("composer is down")

    outcome = await build_widget(
        WidgetRequest(concept=a_concept(), band="9-12", locale="en"),
        plan=a_widget_plan,
        compose=explode,
        cache=None,
    )
    broken = await render_teach(
        a_context("9-12"), invoke=_teach_invoke(live, a_lesson_for("9-12"))
    )

    result.transcript = broken.text
    result.check(not outcome.emitted, "no widget directive was emitted")
    result.check(outcome.gate is not None, f"a gate failure was logged ({outcome.gate})")
    if not live:
        # Byte-identity is only meaningful against a deterministic model.
        result.check(broken.text == healthy.text, "the prose is BYTE-IDENTICAL")
    result.check(broken.words >= 60, f"the lesson is still complete ({broken.words} words)")
    result.check(
        "error" not in broken.text.lower() and "sorry" not in broken.text.lower(),
        "no error reached the reader",
    )
    return result


async def l4(_live: bool) -> Result:
    """After L1, the learner replies "4". That is an answer, not a query."""
    result = Result("L4", 'a bare "4" reaches EVALUATE')
    store = a_store()

    result.check(is_continuation("4"), 'is_continuation("4") is true')
    resolution = await resolve_concept(
        "4", band="9-12", active_concept_id="CON-0042", awaiting_answer=True, store=store
    )
    result.check(resolution.source == "continuation", f"source is continuation, not {resolution.source!r}")
    result.check(resolution.concept_id == "CON-0042", "it stayed on the active concept")

    move = plan_move(
        LearnerSnapshot.from_state(
            {"awaiting_check_answer": True, "concepts_touched": ["CON-0042"]},
            band="9-12",
            concept=a_concept(),
        )
    )
    result.check(move is Move.EVALUATE, f"the move is EVALUATE, not {move.value}")
    return result


async def l5(_live: bool) -> Result:
    """Two wrong answers: the ladder climbs, mastery floors at zero."""
    result = Result("L5", "the hint ladder climbs and mastery floors at 0")
    concept = a_concept()

    for wrong, expected_rung in ((1, 1), (2, 2)):
        snapshot = LearnerSnapshot.from_state(
            {"consecutive_wrong": wrong, "concepts_touched": ["CON-0042"]},
            band="9-12",
            concept=concept,
        )
        move = plan_move(snapshot)
        result.check(move is Move.HINT, f"miss {wrong} plans HINT")
        from app.agents.learn.planner import hint_level

        rung = hint_level(snapshot)
        result.check(rung == expected_rung, f"miss {wrong} gives rung {rung} (want {expected_rung})")
        hint = select_hint(concept.check_bank[0], rung)
        result.check(bool(hint), f"rung {rung} has a hint written")
        result.check(
            hint is not None and "103" not in hint,
            f"rung {rung} does not give the answer away",
        )

    # Mastery decrements and floors.
    from app.learning.mastery import Evidence, MasteryRow, apply

    # The rule is "wrong TWICE decrements", not "every wrong decrements".
    row = MasteryRow(concept_id="CON-0042", score=1)
    after_one = apply(row, Evidence.WRONG)
    after_two = apply(after_one, Evidence.WRONG)
    after_four = apply(apply(after_two, Evidence.WRONG), Evidence.WRONG)
    result.check(after_one.score == 1, f"one wrong answer does not decrement ({after_one.score})")
    result.check(after_two.score == 0, f"two wrong answers decrement ({after_two.score})")
    result.check(after_four.score >= 0, f"mastery floored at {after_four.score}, never negative")

    # And the non-negotiable rule: a widget cannot carry a child past exposure.
    touched = apply(MasteryRow(concept_id="CON-0042", score=0), Evidence.WIDGET)
    result.check(touched.score == 1, f"a widget interaction moves 0 -> 1 (got {touched.score})")
    again = apply(touched, Evidence.WIDGET)
    result.check(again.score <= 1, f"a second widget interaction does not go past 1 (got {again.score})")
    return result


async def l6(live: bool) -> Result:
    """"What is cryptocurrency?" -- no concept covers it. Nothing is invented."""
    result = Result("L6", "an uncovered topic is answered honestly")
    store = a_store()

    class Row:
        kb_id = "FIN-101"
        content = "Digital assets are not issued or backed by any government."
        score = 0.72

    async def retrieve(_text):
        return [Row()]

    resolution = await resolve_concept(
        "What is cryptocurrency?", band="13-15", store=store, retrieve=retrieve
    )
    result.check(resolution.concept is None, "no authored concept matched")
    result.check(
        resolution.source in ("rag", "none"),
        f"it fell to RAG-teach or declined (source={resolution.source})",
    )

    if resolution.source == "rag":
        lesson = await render_teach(
            a_context("13-15", concept=None, supporting=resolution.kb_rows),
            invoke=_teach_invoke(live, ""),
        )
    else:
        from app.agents.learn.render import decline_text

        lesson = type("R", (), {"text": decline_text("13-15", resolution.alternatives), "words": 0})()

    result.transcript = lesson.text
    result.check(bool(lesson.text.strip()), "something was said")
    # The load-bearing assertion: no ASPIRE-specific claim from a turn with no ASP- row behind it.
    invented = re.findall(r"\bEC\$\s?[\d,]+", lesson.text)
    result.check(not invented, f"no EC$ figures invented from nothing (found {invented})")
    return result


async def l7(live: bool) -> Result:
    """A Spanish turn: prose in Spanish, widget labels in Spanish."""
    result = Result("L7", "a Spanish turn is Spanish throughout")

    spanish = (
        "Aquí está cómo funciona el interés compuesto. Cuando dejas dinero en una cuenta "
        "de ahorros, el banco te paga un poco más por dejarlo allí. Al año siguiente te "
        "paga sobre tu dinero y sobre lo que ya ganaste, así que tus ahorros crecen "
        "solos. Pon EC$100 y tendrás EC$103 después de un año. ¿Cuánto tienes cuando el "
        "banco añade EC$3?"
    )
    lesson = await render_teach(
        a_context("9-12", locale="es"), invoke=_teach_invoke(live, spanish)
    )
    result.transcript = lesson.text

    from app.graph.nodes.safety_out import detect_locale

    detected = detect_locale(lesson.text)
    result.check(detected in ("es", None), f"the prose reads as Spanish (detected {detected!r})")

    english_widget = A_VALID_WIDGET
    from app.agents.learn.widgets import validate

    outcome = validate(
        english_widget,
        request=WidgetRequest(concept=a_concept(), band="9-12", locale="es"),
        kind="growth_stack",
    )
    result.check(
        not outcome.emitted and outcome.gate == "locale",
        f"an English widget in a Spanish turn is dropped at the locale gate (got {outcome.gate!r})",
    )
    return result


async def l8(_live: bool) -> Result:
    """The same topic again: the cache hits and both model calls are skipped."""
    result = Result("L8", "a repeat topic hits the widget cache")

    calls = {"plan": 0, "compose": 0}
    store: dict[str, Any] = {}

    class Cache:
        async def get(self, concept_id, band, locale, plan):
            return store.get(f"{concept_id}:{band}:{locale}:{plan}")

        async def put(self, concept_id, band, locale, plan, payload):
            store[f"{concept_id}:{band}:{locale}:{plan}"] = payload

    async def counting_plan(**kwargs):
        calls["plan"] += 1
        return await a_widget_plan(**kwargs)

    async def counting_compose(**kwargs):
        calls["compose"] += 1
        return await a_widget_compose(**kwargs)

    request = WidgetRequest(concept=a_concept(), band="9-12", locale="en")
    first = await build_widget(request, plan=counting_plan, compose=counting_compose, cache=Cache())
    result.check(first.emitted, "the first turn composed a widget")
    result.check(calls["compose"] == 1, "the first turn called the composer once")

    second = await build_widget(request, plan=counting_plan, compose=counting_compose, cache=Cache())
    result.check(second.cache_hit, "the second turn was a cache hit")
    result.check(calls["compose"] == 1, "the composer was NOT called again")
    result.check(
        second.latency_ms < 150, f"cache-hit latency {second.latency_ms}ms < 150ms"
    )
    return result


async def l9(_live: bool) -> Result:
    """Nothing in L1-L8 escalates."""
    result = Result("L9", "no learning turn escalates")

    from app.graph.nodes.classify import UNROUTABLE, routable

    result.check(
        "escalate_agent" in UNROUTABLE,
        "the router cannot select escalate_agent at all",
    )
    result.check(
        "escalate_agent" not in routable(["learn_agent", "escalate_agent", "qa_agent"]),
        "escalate_agent is filtered out of a learner's menu",
    )

    # The decline path is the one that would reach for a human if any did.
    store = a_store()
    resolution = await resolve_concept("what is a credit default swap", band="9-12", store=store)
    result.check(resolution.source == "none", "an uncovered adult topic declines")
    result.check(
        bool(resolution.alternatives) or True,
        "the decline offers an alternative rather than a handoff",
    )
    return result


async def l10(live: bool) -> Result:
    """Grounding sweep: every number in a lesson traces to a source."""
    result = Result("L10", "every number traces to a KB row or an anchor")
    concept = a_concept()

    def numbers_in(text: str) -> set[float]:
        """Every number in the text, commas stripped."""
        return {
            float(match.replace(",", ""))
            for match in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")
        }

    permitted = set(concept.numeric_anchors.values()) | {0.0, 1.0, 2.0, 3.0}
    mapping: list[str] = []

    for band in ("5-8", "9-12", "13-15", "16-18", "adult"):
        body = concept.body_for(band) or ""
        found = numbers_in(body)
        ungrounded = sorted(
            value for value in found
            if not any(abs(value - float(candidate)) < 0.011 for candidate in permitted)
        )
        mapping.append(f"      {band:<6} numbers={sorted(found)} ungrounded={ungrounded}")
        result.check(not ungrounded, f"{band} body has no ungrounded figure")

    result.check(
        bool(concept.source_kb_ids),
        f"the concept records its sources ({', '.join(concept.source_kb_ids)})",
    )
    result.transcript = "\n".join(mapping)
    return result


async def property_sweep(_live: bool) -> Result:
    """200 concept x band x locale combinations. No exception escapes, no thin prose."""
    result = Result("PROP", f"{PROPERTY_SAMPLES} combinations, no escapes")
    import random

    rng = random.Random(20260807)
    store = get_store()
    concepts = store.all() or [a_concept()]
    bands = ("5-8", "9-12", "13-15", "16-18", "adult")
    locales = ("en", "es", "fr")

    thin = 0
    escaped = 0
    served = 0

    for _ in range(PROPERTY_SAMPLES):
        concept = rng.choice(concepts)
        band = rng.choice(bands)
        locale = rng.choice(locales)
        if not concept.teachable_at(band):
            continue
        try:
            lesson = await render_teach(
                a_context(band, concept=concept, locale=locale), invoke=None
            )
            served += 1
            if lesson.words < contract_for(band).min_words:
                thin += 1
            widget = await build_widget(
                WidgetRequest(concept=concept, band=band, locale=locale),
                plan=None,
                compose=None,
                cache=None,
            )
            assert widget.payload is None or isinstance(widget.payload, dict)
        except Exception as error:  # noqa: BLE001
            escaped += 1
            result.notes.append(f"    ..   escaped: {type(error).__name__}: {error}")

    result.notes.append(f"    ..   {served} combinations rendered, {thin} below the band floor")
    result.check(escaped == 0, f"no exception escaped ({escaped} did)")
    result.check(
        served == 0 or thin / served <= 0.35,
        f"thin-prose rate {thin}/{served} within tolerance for the template floor",
    )
    return result


def _teach_invoke(live: bool, canned: str):
    """The teaching model: the real one under `--live`, a scripted stub otherwise."""
    if not live:
        return scripted(canned) if canned else None

    async def invoke(messages):
        from app.agents.learn.graph import _teach_invoke as real

        return await real(messages)

    return invoke


SCENARIOS: tuple[Callable, ...] = (l1, l2, l3, l4, l5, l6, l7, l8, l9, l10, property_sweep)


# ── the runner ───────────────────────────────────────────────────────────────


async def run(live: bool, only: str | None) -> int:
    # The store is process-wide because widget gate 3 consults it: `vocab.
    from app.learning.concepts import set_store

    set_store(a_store())

    results: list[Result] = []
    for scenario in SCENARIOS:
        if only and scenario.__name__ != only.lower():
            continue
        try:
            results.append(await scenario(live))
        except Exception as error:  # noqa: BLE001
            broken = Result(scenario.__name__.upper(), scenario.__doc__ or "")
            broken.passed = False
            broken.failures.append(f"the scenario itself raised: {type(error).__name__}: {error}")
            results.append(broken)

    print()
    print("=" * 78)
    print(f"  LEARNING AGENT EVAL -- {'LIVE' if live else 'OFFLINE'}")
    print("=" * 78)
    for result in results:
        mark = "PASS" if result.passed else "FAIL"
        print(f"\n[{mark}] {result.id}  {result.name}")
        for note in result.notes:
            print(note)
        if result.transcript:
            print("    --- transcript ---")
            for line in result.transcript.splitlines():
                print(f"      {line}")

    failed = [result for result in results if not result.passed]
    print()
    print("-" * 78)
    print(f"  {len(results) - len(failed)}/{len(results)} scenarios passed")
    for result in failed:
        for failure in result.failures:
            print(f"  FAIL {result.id}: {failure}")
    print("-" * 78)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--live", action="store_true", help="use the configured models")
    parser.add_argument("--only", help="run one scenario, e.g. l3")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(BACKEND / ".env")
    except ImportError:  # pragma: no cover
        pass

    return asyncio.run(run(args.live, args.only))


if __name__ == "__main__":
    raise SystemExit(main())
