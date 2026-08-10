"""The planner: what it offers, what it refuses, and how often it is right."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from app.safety import vocab  # noqa: E402
from app.widgets import planner  # noqa: E402
from app.widgets.validate import BAND_CONTROL_CAP, BAND_KINDS  # noqa: E402

CASES = [
    json.loads(line)
    for line in (Path(__file__).resolve().parents[2] / "evals" / "widgets.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]

SELECTION_TARGET = 0.80
OVER_TRIGGER_LIMIT = 0.15


def replying(payload: str):
    async def invoke(system: str, user: str) -> str:
        return payload

    return invoke


class TestTheEvalSetIsWellFormed:
    def test_there_are_a_hundred(self):
        assert len(CASES) == 100

    def test_it_spans_four_bands_and_three_locales(self):
        assert {case["age_band"] for case in CASES} == {
            "5-8",
            "9-12",
            "13-15",
            "16-18",
        }
        assert {case["locale"] for case in CASES} == {"en", "es", "fr"}

    def test_a_third_of_it_is_null(self):
        """A set with no nulls cannot measure over-triggering at all."""
        nulls = sum(1 for case in CASES if case["ideal"] is None)
        assert 0.25 <= nulls / len(CASES) <= 0.45

    def test_every_label_is_reachable_at_its_own_band(self):
        """A label the band forbids is an impossible test, not a hard one."""
        for case in CASES:
            if case["ideal"] is None:
                continue
            assert case["ideal"] in BAND_KINDS[case["age_band"]], case["id"]

    def test_no_five_to_eight_row_expects_a_simulator(self):
        for case in CASES:
            if case["age_band"] == "5-8":
                assert case["ideal"] != "simulator", case["id"]


class TestTheMenu:
    """Band filtering happens BEFORE the prompt, which is what makes it hold."""

    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15", "16-18", "adult"])
    def test_the_menu_never_offers_a_kind_the_band_excludes(self, band):
        offered = planner.kinds_for(band, "save", [])
        assert set(offered) <= BAND_KINDS[band]

    def test_a_five_to_eight_is_never_offered_a_simulator(self):
        assert "simulator" not in planner.kinds_for("5-8", "save", [])
        assert BAND_CONTROL_CAP["5-8"] == 0

    def test_a_nine_to_twelve_is_never_offered_a_simulator(self):
        """Coins you can count beat a number that changes, at this age."""
        assert "simulator" not in planner.kinds_for("9-12", "save", [])

    def test_a_concept_off_the_ladder_offers_nothing(self):
        """A widget about a concept they are not being taught is a widget about something else."""
        assert planner.kinds_for("5-8", "compound_interest", []) == []
        assert planner.kinds_for("9-12", "inflation", []) == []

    def test_recent_kinds_are_withheld(self):
        offered = planner.kinds_for("9-12", "save", ["compare", "reveal_cards"])
        assert "compare" not in offered
        assert "reveal_cards" not in offered

    def test_withholding_never_empties_the_menu(self):
        """A repeated primitive beats no visual where one genuinely helps."""
        every = list(BAND_KINDS["5-8"])
        assert planner.kinds_for("5-8", "save", every)


class TestTheBandTable:
    """The one concept the specification fixes by hand."""

    @pytest.mark.parametrize(
        ("band", "kind"),
        [
            ("5-8", None),
            ("9-12", "growth_stack"),
            ("13-15", "simulator"),
            ("16-18", "simulator"),
        ],
    )
    def test_compound_interest_by_band(self, band, kind):
        fixed, chosen, _about = planner.forced_kind("compound_interest", band)
        assert fixed
        assert chosen == kind

    def test_a_five_to_eight_is_redirected_to_saving(self):
        fixed, kind, about = planner.forced_kind("compound_interest", "5-8")
        assert fixed and kind is None and about == "save"

    def test_a_nine_to_twelve_gets_a_widget_about_interest_not_compounding(self):
        """The concept it is ABOUT is not the concept that was asked about."""
        _fixed, _kind, about = planner.forced_kind("compound_interest", "9-12")
        assert about == "interest"
        assert vocab.is_allowed_concept(about, "9-12")

    @pytest.mark.asyncio
    async def test_the_table_costs_no_model_call(self):
        calls: list[str] = []

        async def counting(system: str, user: str) -> str:
            calls.append(user)
            return '{"kind": null}'

        plan = await planner.make_planner(counting)(
            user_message="what is compound interest",
            concept_id="compound_interest",
            age_band="9-12",
        )
        assert plan.kind == "growth_stack"
        assert calls == []


@pytest.mark.asyncio
class TestContainment:
    """No planner output can produce a band violation."""

    @pytest.mark.parametrize(
        "raw",
        [
            '{"kind": "simulator", "rationale": "x"}',
            '{"kind": "hologram", "rationale": "x"}',
            '{"kind": "", "rationale": "x"}',
            "not json",
            "",
            '{"kind": 42}',
        ],
    )
    @pytest.mark.parametrize("band", ["5-8", "9-12"])
    async def test_a_bad_or_forbidden_choice_serves_prose(self, raw, band):
        plan = await planner.make_planner(replying(raw))(
            user_message="what is saving",
            concept_id="save",
            age_band=band,
        )
        assert plan.kind is None or plan.kind in BAND_KINDS[band]

    async def test_an_outage_costs_a_widget_not_a_turn(self):
        async def exploding(system: str, user: str) -> str:
            raise RuntimeError("provider down")

        plan = await planner.make_planner(exploding)(
            user_message="what is saving", concept_id="save", age_band="9-12"
        )
        assert plan.kind is None

    async def test_widgets_disabled_means_no_widget(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "widgets_enabled", False)
        plan = await planner.make_planner(replying('{"kind":"compare"}'))(
            user_message="what is saving", concept_id="save", age_band="9-12"
        )
        assert plan.kind is None

    async def test_null_is_understood_in_every_form_a_model_writes_it(self):
        for raw in ['{"kind": null}', '{"kind": "null"}', '{"kind": "none"}', '{"kind": ""}']:
            plan = await planner.make_planner(replying(raw))(
                user_message="ok", concept_id="save", age_band="9-12"
            )
            assert plan.kind is None, raw


class TestTheCompositionPrompt:
    def test_it_carries_one_schema_and_not_nine(self):
        """The token saving the split exists for."""
        prompt = planner.composition_prompt("growth_stack", "9-12", "en", "interest")
        assert "growth_stack" in prompt
        for other in ("sort_buckets", "flow_diagram", "reveal_cards", "allocator"):
            assert f'"{other}"' not in prompt

    def test_it_names_the_bands_banned_words(self):
        prompt = planner.composition_prompt("growth_stack", "9-12", "en", "interest")
        assert "compound" in prompt
        assert "may NOT use" in prompt

    def test_it_names_the_control_cap(self):
        assert "At most 2 control" in planner.composition_prompt(
            "simulator", "13-15", "en", "goal"
        )
        assert "At most 4 control" in planner.composition_prompt(
            "simulator", "16-18", "en", "compound interest"
        )

    def test_it_requires_the_screen_reader_text(self):
        prompt = planner.composition_prompt("compare", "5-8", "en", "save")
        assert "a11y_text" in prompt
        assert "screen reader" in prompt

    def test_it_carries_worked_examples_for_that_kind_and_band(self):
        prompt = planner.composition_prompt("growth_stack", "9-12", "en", "interest")
        assert "Examples:" in prompt
        assert "reveal_line" in prompt

    def test_examples_fall_back_downward_not_upward(self):
        """An older reader shown a younger example is fine."""
        assert planner.fewshots("compare", "13-15")  # inherits 9-12
        assert planner.fewshots("growth_stack", "16-18")  # inherits 9-12

    def test_the_null_examples_are_shown_on_every_planning_call(self):
        """Showing a model what "no" looks like beats telling it "no" is allowed."""
        assert "-> null" in planner.null_examples()


# ── measured against a real model ────────────────────────────────────────────


def _model_available() -> bool:
    from app.config import get_settings
    from app.graph.nodes.classify import resolve_classifier_model

    settings = get_settings()
    provider = resolve_classifier_model().split(":", 1)[0].lower()
    return bool(
        {
            "anthropic": settings.anthropic_api_key,
            "openai": settings.openai_api_key,
        }.get(provider)
    )


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.skipif(not _model_available(), reason="no API key for the planner model")
async def test_planner_accuracy_and_over_trigger(capsys):
    """Reports selection accuracy, over-trigger rate and band violations."""
    from app.graph.nodes.classify import default_invoke

    plan = planner.make_planner(default_invoke)
    correct = 0
    over_triggered = 0
    should_be_null = 0
    violations: list[str] = []
    misses: list[str] = []

    for case in CASES:
        result = await plan(
            user_message=case["question"],
            concept_id=case["concept_id"],
            age_band=case["age_band"],
            locale=case["locale"],
        )

        if result.kind is not None and result.kind not in BAND_KINDS[case["age_band"]]:
            violations.append(f"{case['id']}: {result.kind} at {case['age_band']}")

        if case["ideal"] is None:
            should_be_null += 1
            if result.kind is not None:
                over_triggered += 1

        if result.kind == case["ideal"]:
            correct += 1
        else:
            misses.append(
                f"{case['id']} [{case['age_band']}/{case['locale']}] "
                f"{case['question']!r} -> {result.kind} (want {case['ideal']})"
            )

    accuracy = correct / len(CASES)
    over_trigger = over_triggered / max(1, should_be_null)

    with capsys.disabled():
        print(f"\nwidget selection accuracy: {accuracy:.1%} ({correct}/{len(CASES)})")
        print(f"over-trigger rate:         {over_trigger:.1%} ({over_triggered}/{should_be_null})")
        print(f"band violations:           {len(violations)}")
        for line in misses[:20]:
            print(f"  miss  {line}")

    assert not violations, violations
    assert accuracy > SELECTION_TARGET, f"{accuracy:.1%} is below {SELECTION_TARGET:.0%}"
    assert over_trigger < OVER_TRIGGER_LIMIT, (
        f"{over_trigger:.1%} is above {OVER_TRIGGER_LIMIT:.0%}"
    )
