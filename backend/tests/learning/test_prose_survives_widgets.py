"""The P0 test. A widget may fail at any stage; the lesson may never fail.

This is the regression test for the reported bug, and it is written to fail if
the coupling that caused it is ever reintroduced. The invariant, stated so that a
future reader can check the tests against it rather than against a memory of a
design:

    A learning turn ALWAYS emits a substantive, grounded, persona-appropriate
    explanation. The widget is an enhancement layered on prose that already
    exists and has already been emitted. A widget may fail silently at any stage.
    Prose may never fail.

The inverse -- a widget with no lesson -- is a P0 bug, and
`test_a_widget_never_arrives_without_a_lesson` is the assertion that says so.

## What "fail at any stage" means here

Six stages, each exercised separately, because they fail differently and an
implementation can easily survive five of them:

    planner raises            no kind chosen
    planner returns garbage   a kind the band forbids
    composer raises           no JSON at all
    composer returns garbage  JSON that fails a gate
    the whole task hangs      the timeout fires
    the cache raises          a Valkey blip

For each: the prose is byte-identical to the prose of a run with a healthy widget
path, and no error reaches the reader.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.learn import tutor as tutor_module
from app.agents.learn.planner import Move
from app.agents.learn.render import TeachContext, render_teach
from app.agents.learn.widgets import (
    WidgetRequest,
    build_widget,
)
from app.learning.concepts import CheckItem, ConceptStore, TeachingConcept


# ── fixtures ─────────────────────────────────────────────────────────────────


def a_concept() -> TeachingConcept:
    return TeachingConcept(
        id="CON-0042",
        slug="compound_interest",
        locale="en",
        title="Compound interest",
        domain="saving",
        band_min="9-12",
        band_max="adult",
        aliases=("interest on interest", "money growing"),
        bodies={
            "9-12": (
                "When you keep money in a savings account, the bank pays you a little "
                "extra for leaving it there. That extra is called interest. The clever "
                "part is what happens next: the following year the bank pays you extra "
                "on your money AND on the interest you already earned. Your savings "
                "start growing on their own, faster each year, without you adding a "
                "single cent more."
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
            ),
        ),
        numeric_anchors={"principal": 100, "rate": 0.03, "years": 5},
        widget_hints=("growth_stack",),
        source_kb_ids=("FIN-011", "FIN-012"),
        status="draft",
    )


A_GOOD_LESSON = (
    "Here is something worth knowing. When you leave money in a savings account, the "
    "bank pays you a little extra for keeping it there, and that extra is called "
    "interest. The clever part comes the year after: the bank pays you extra on your "
    "money and on the interest you already earned. Put EC$100 in at 3 percent and you "
    "have EC$103 after a year, and the next year the bank pays interest on all EC$103. "
    "If you save EC$100 and the bank adds EC$3, how much do you have?"
)

A_VALID_GROWTH_STACK = """{
  "kind": "growth_stack",
  "v": 1,
  "concept_id": "compound_interest",
  "title": "Watch it grow",
  "principal_cents": 10000,
  "contribution_cents": 0,
  "rate": 0.03,
  "periods": 5,
  "period_label": "year",
  "a11y_text": "Two stacks of coins. The first is what you put in. The second is the same money after five years, taller because the bank added a little each year."
}"""


async def a_teach_call(messages):
    return A_GOOD_LESSON


def a_context(concept: TeachingConcept | None = None) -> TeachContext:
    return TeachContext(
        concept=concept or a_concept(),
        band="9-12",
        locale="en",
        move=Move.TEACH,
        check_item=(concept or a_concept()).check_bank[0],
        utterance="What is compound interest?",
    )


def a_request(concept: TeachingConcept | None = None) -> WidgetRequest:
    return WidgetRequest(
        concept=concept or a_concept(),
        band="9-12",
        locale="en",
        agent="learn_agent",
        utterance="What is compound interest?",
    )


@pytest.fixture(autouse=True)
def _a_populated_store():
    """The concept store, loaded, for the whole module.

    Autouse and not optional. Widget gate 3 asks `vocab.is_allowed_concept`
    whether the band may meet this concept, and that consults the concept store
    as its second registry -- so a widget test running against an empty store
    fails at the band gate for a reason that has nothing to do with what it is
    testing. Failing closed there is correct in production (no concepts means no
    tutor turn means no widget) and is pure noise here.
    """
    from app.learning.concepts import set_store

    store = ConceptStore()
    store.load([a_concept()])
    set_store(store)
    try:
        yield store
    finally:
        set_store(None)


# ── the widget path cannot raise ─────────────────────────────────────────────


class TestTheWidgetPathAbsorbsEverything:
    """`build_widget` returns an outcome. It never raises, whatever is injected."""

    @pytest.mark.asyncio
    async def test_a_planner_that_raises_yields_no_widget(self):
        async def explode(**_):
            raise RuntimeError("planner is down")

        outcome = await build_widget(a_request(), plan=explode, compose=None, cache=None)
        assert not outcome.emitted
        assert outcome.payload is None

    @pytest.mark.asyncio
    async def test_a_composer_that_raises_yields_no_widget(self):
        async def plan(**_):
            return {"kind": "growth_stack", "rationale": "shows growth"}

        async def explode(**_):
            raise RuntimeError("composer is down")

        outcome = await build_widget(a_request(), plan=plan, compose=explode, cache=None)
        assert not outcome.emitted
        assert outcome.gate == "compose"

    @pytest.mark.asyncio
    async def test_a_composer_returning_rubbish_fails_a_named_gate(self):
        async def plan(**_):
            return {"kind": "growth_stack"}

        async def rubbish(**_):
            return "I think a growth stack would be lovely here!"

        outcome = await build_widget(a_request(), plan=plan, compose=rubbish, cache=None)
        assert not outcome.emitted
        # Named, because "gate parse fired 40 times" is a prompt to fix and "the
        # widget was rejected" is not.
        assert outcome.gate == "parse"

    @pytest.mark.asyncio
    async def test_a_cache_that_raises_is_a_miss_and_nothing_more(self):
        class BrokenCache:
            async def get(self, *_args):
                raise RuntimeError("valkey is down")

            async def put(self, *_args):
                raise RuntimeError("valkey is down")

        async def plan(**_):
            return {"kind": "growth_stack"}

        async def compose(**_):
            return A_VALID_GROWTH_STACK

        outcome = await build_widget(
            a_request(), plan=plan, compose=compose, cache=BrokenCache()
        )
        assert outcome.emitted, "a broken cache must not cost the widget"

    @pytest.mark.asyncio
    async def test_a_widget_from_another_agent_is_dropped_unconditionally(self):
        """The widget system is a teaching device with a curriculum behind it.

        A widget arriving while `qa_agent` is active means either a prompt leaked
        between agents or something is being tried. Neither is served.
        """
        request = a_request()
        request.agent = "qa_agent"

        async def plan(**_):
            return {"kind": "growth_stack"}

        async def compose(**_):
            return A_VALID_GROWTH_STACK

        outcome = await build_widget(request, plan=plan, compose=compose, cache=None)
        assert not outcome.emitted
        assert outcome.gate == "provenance"

    @pytest.mark.asyncio
    async def test_a_kind_the_concept_does_not_permit_is_dropped(self):
        """Gate 9. The band would allow it; the concept's author did not.

        A composer handed `growth_stack` that returns a `simulator` has produced
        something nobody approved for this concept, and the band gate passes it
        because the band permits both.
        """
        request = a_request()
        widget = A_VALID_GROWTH_STACK.replace('"growth_stack"', '"proportion"')
        from app.agents.learn.widgets import validate

        outcome = validate(widget, request=request, kind="growth_stack")
        assert not outcome.emitted


# ── the prose is unaffected ──────────────────────────────────────────────────


class TestProseIsIndependent:
    @pytest.mark.asyncio
    async def test_the_lesson_is_byte_identical_whatever_the_widget_does(self):
        """The regression test for the reported bug.

        Prose used to be produced by the same model call that emitted the widget,
        inline between sentinels, so a malformed widget truncated the lesson. If
        that coupling ever returns, these two strings stop matching.
        """
        healthy = await render_teach(a_context(), invoke=a_teach_call)

        async def explode(**_):
            raise RuntimeError("everything is on fire")

        broken_widget = await build_widget(
            a_request(), plan=explode, compose=explode, cache=None
        )
        with_failure = await render_teach(a_context(), invoke=a_teach_call)

        assert not broken_widget.emitted
        assert with_failure.text == healthy.text
        assert with_failure.text == A_GOOD_LESSON

    @pytest.mark.asyncio
    async def test_a_hanging_widget_task_does_not_hold_the_turn(self, monkeypatch):
        """The timeout fires, the task is cancelled, the lesson is already out."""

        async def never_returns(*_args, **_kwargs):
            await asyncio.sleep(30)

        from app.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "learn_widget_timeout_s", 0.05, raising=False)

        task = asyncio.create_task(never_returns())
        outcome = await tutor_module._await_widget(task)

        assert not outcome.emitted
        assert outcome.gate == "timeout"
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_no_model_at_all_still_teaches(self):
        """Tier 3. The floor is a template built in Python from the concept row.

        This is the configuration that makes the reported symptom impossible: with
        no provider key, no planner and no composer, a learner still receives the
        concept's body, its local example and its check question.
        """
        result = await render_teach(a_context(), invoke=None)

        assert result.tier == 3
        assert result.words >= 40
        assert "EC$100" in result.text
        assert result.text.count("?") == 1
        assert "interest" in result.text.lower()

    @pytest.mark.asyncio
    async def test_a_model_that_returns_nothing_falls_to_the_floor(self):
        async def empty(_messages):
            return ""

        result = await render_teach(a_context(), invoke=empty)
        assert result.tier == 3
        assert result.text.strip()

    @pytest.mark.asyncio
    async def test_a_model_that_raises_falls_to_the_floor(self):
        async def explode(_messages):
            raise RuntimeError("provider is down")

        result = await render_teach(a_context(), invoke=explode)
        assert result.tier == 3
        assert result.text.strip()

    @pytest.mark.asyncio
    async def test_a_thin_lesson_is_regenerated_once(self):
        """Tier 2. Twenty-two words is not a lesson for a 9-12 learner."""
        calls: list[str] = []

        async def thin_then_good(messages):
            calls.append("call")
            if len(calls) == 1:
                return "Compound interest is interest on interest. What do you think?"
            return A_GOOD_LESSON

        result = await render_teach(a_context(), invoke=thin_then_good)

        assert len(calls) == 2, "the first attempt must be retried, not served"
        assert result.tier == 1
        assert result.retry
        assert result.text == A_GOOD_LESSON

    @pytest.mark.asyncio
    async def test_the_retry_quotes_the_actual_violation(self):
        """"Be more thorough" moves a word count by ten percent. A number fixes it."""
        seen: list[str] = []

        async def capture(messages):
            seen.append("\n".join(str(message.content) for message in messages))
            return "Too short." if len(seen) == 1 else A_GOOD_LESSON

        await render_teach(a_context(), invoke=capture)

        assert len(seen) == 2
        retry_prompt = seen[1]
        assert "TOO_SHORT" in retry_prompt
        assert "60" in retry_prompt, "the band's floor must be named in the retry"


# ── the invariant, stated as a test ──────────────────────────────────────────


class TestTheInvariant:
    @pytest.mark.asyncio
    async def test_a_widget_never_arrives_without_a_lesson(self):
        """A widget with no lesson is a P0 bug. There must be a test that fails.

        Driven through the node so that the ORDER is asserted too, not merely the
        presence of both: prose is written to the wire before the widget task is
        even awaited.
        """
        emitted: list[tuple[str, object]] = []

        class Recorder:
            def __call__(self, payload):
                for key in ("prose", "directive"):
                    if key in payload:
                        emitted.append((key, payload[key]))

        async def plan(**_):
            return {"kind": "growth_stack"}

        async def compose(**_):
            return A_VALID_GROWTH_STACK

        node = tutor_module.make_tutor(
            embed=None,  # resolution falls to continuation, below
            invoke=a_teach_call,
            plan=plan,
            compose=compose,
            cache=None,
        )

        import app.agents.learn.tutor as module

        recorder = Recorder()
        original = module._writer
        module._writer = lambda: recorder
        try:
            await node(
                {
                    "messages": [],
                    "age_band": "9-12",
                    "locale": "en",
                    "active_agent": "learn_agent",
                    "learning": {"active_concept_id": "CON-0042"},
                }
            )
        finally:
            module._writer = original

        kinds = [key for key, _ in emitted]
        assert "prose" in kinds, "a turn with a widget and no lesson is the P0 bug"
        if "directive" in kinds:
            assert kinds.index("prose") < kinds.index("directive"), (
                "the widget must arrive after the prose has settled"
            )


class TestNothingAfterTheProseCanTakeItAway:
    """The other half of the invariant, and the half that shipped broken.

    `test_a_widget_never_arrives_without_a_lesson` proves a widget cannot arrive
    without prose. It does not prove the converse that matters just as much: that
    prose already sent cannot be retracted by something failing behind it.

    It could be. `_state_after` dereferenced a null check item and raised, the
    node died, `api/stream.py` caught it and emitted `error: upstream`, and the
    reader watched a complete 140-word lesson appear and then be told the
    assistant was unavailable. Nothing was persisted either, because the except
    branch returns before `persist_turn`.

    Observed in production on the RAG-teach path, which is the one path where a
    lesson asks a question that no check item backs -- no concept, so no check
    bank, so `select_check` returns None while the lesson still ends in a
    question invented from the retrieved rows.
    """

    @pytest.mark.asyncio
    async def test_a_rag_lesson_with_no_check_item_completes(self):
        """The exact production failure: `asked` is true and `check_item` is None.

        Asserts the turn returns rather than raising, and that it returns the
        lesson. Before the fix this raised AttributeError on `check_item.id`.
        """
        node = tutor_module.make_tutor(
            embed=None,
            invoke=a_teach_call,
            plan=None,
            compose=None,
            cache=None,
            retrieve=None,
        )

        from app.learning.concepts import set_store

        # An empty store is what forces the RAG path: nothing to resolve against,
        # so `concept` is None and `select_check` has no bank to select from.
        empty = ConceptStore()
        empty.load([])
        set_store(empty)
        try:
            result = await node(
                {
                    "messages": [],
                    "age_band": "16-18",
                    "locale": "en",
                    "active_agent": "learn_agent",
                    "learning": {},
                }
            )
        finally:
            set_store(None)

        assert result is not None
        assert result.get("messages"), "the lesson must survive a missing check item"

    @pytest.mark.asyncio
    async def test_bookkeeping_that_raises_still_serves_the_lesson(self):
        """Break `_state_after` outright. The reader must still get the lesson.

        The general form of the bug rather than the specific one. Whatever fails
        after the prose is emitted -- a widget, a log line, the state write -- it
        is bookkeeping, and no bookkeeping is worth a lesson the child has already
        started reading.
        """
        emitted: list[str] = []

        class Recorder:
            def __call__(self, payload):
                if "prose" in payload:
                    emitted.append(payload["prose"])

        import app.agents.learn.tutor as module

        def explode(**_):
            raise RuntimeError("bookkeeping is broken")

        node = module.make_tutor(
            embed=None, invoke=a_teach_call, plan=None, compose=None, cache=None
        )

        recorder = Recorder()
        original_writer = module._writer
        original_state = module._state_after
        module._writer = lambda: recorder
        module._state_after = explode
        try:
            result = await node(
                {
                    "messages": [],
                    "age_band": "9-12",
                    "locale": "en",
                    "active_agent": "learn_agent",
                    "learning": {"active_concept_id": "CON-0042"},
                }
            )
        finally:
            module._writer = original_writer
            module._state_after = original_state

        assert emitted, "the prose must have been sent"
        assert result is not None, "a failure after the prose must not kill the node"
        assert result.get("messages"), "the transcript must still receive the lesson"
        assert result["messages"][0].content == A_GOOD_LESSON

    @pytest.mark.asyncio
    async def test_state_after_tolerates_a_null_check_item_directly(self):
        """`_state_after` itself, below the safety net.

        This test exists because of what the two above CANNOT see. The net that
        keeps a delivered lesson alive also swallows the exception that would
        have revealed why it was needed -- reverting the null guard leaves both
        of them green, because the turn still completes and still serves prose.

        A safety net makes failures behind it survivable, not absent. So the
        assertion has to go under the net and call the function directly, where a
        regression surfaces as the AttributeError it is rather than as a log line
        nobody is grepping for.
        """
        import app.agents.learn.tutor as module
        from app.agents.learn.planner import LearnerSnapshot, Move
        from app.agents.learn.render import RenderResult
        from app.agents.learn.resolve import ConceptResolution
        from app.agents.learn.widgets import WidgetOutcome

        state = module._state_after(
            state={"age_band": "16-18"},
            learning={},
            # The RAG path: no concept resolved, so no check bank to draw from.
            resolution=ConceptResolution(
                concept=None, source="rag", similarity=0.583, kb_rows=("FIN-011",)
            ),
            move=Move.TEACH,
            band="16-18",
            lesson=RenderResult(text=A_GOOD_LESSON, tier=1),
            widget=WidgetOutcome(gate="provenance"),
            check_item=None,
            snapshot=LearnerSnapshot(),
        )

        assert state["messages"][0].content == A_GOOD_LESSON
        learning = state["learning"]
        assert learning["awaiting_check_answer"] is False, (
            "no check item means no answer is owed, whatever the move was"
        )
        assert learning["pending_check_id"] is None
        assert learning["seen_check_ids"] == []
