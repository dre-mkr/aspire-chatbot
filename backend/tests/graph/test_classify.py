"""The router, against the one property it must never lose and the one it should hit.

**Containment** is a hard assertion, checked against a deliberately hostile
classifier: one that returns other agents' names, invented names, injections,
malformed JSON and nothing at all. It must be impossible for any of those to
produce a route outside `allowed_agents`.

**Accuracy** is measured, reported, and asserted only when a model is actually
available. It runs against `evals/routing.jsonl` -- forty labelled utterances
spread across the four personas, both identity states, and the mid-flow cases
that stickiness exists for. The target is 85%. Without an API key the accuracy
test skips and the containment tests still run, because containment is a
property of this code and accuracy is a property of a model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.graph.access import allowed_agents
from app.graph.nodes.classify import (
    AGENT_DESCRIPTIONS,
    agent_menu,
    apply_stickiness,
    Classification,
    make_classify,
)
from app.graph.state import initial_state

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

CASES = [
    json.loads(line)
    for line in (Path(__file__).resolve().parents[2] / "evals" / "routing.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]


def state_for(case: dict, **overrides):
    state = initial_state(
        session_id=case["id"],
        user_id=case["user_id"],
        device_id="d",
        persona=case["persona"],
        age_band=case["age_band"],
        account_status=case["account_status"],
    )
    state["allowed_agents"] = allowed_agents(
        case["persona"],
        case["age_band"],
        case["account_status"],
        user_id=case["user_id"],
    )
    state["active_agent"] = case["active_agent"]
    from langchain_core.messages import HumanMessage

    state["messages"] = [HumanMessage(content=case["utterance"])]
    state.update(overrides)
    return state


def replying(text: str):
    async def invoke(system: str, user: str) -> str:
        return text

    return invoke


class TestTheLabelledSetIsWellFormed:
    """The fixture is data; data goes wrong quietly. These keep it honest."""

    def test_there_are_forty(self):
        assert len(CASES) == 40

    def test_ids_are_unique(self):
        assert len({case["id"] for case in CASES}) == 40

    def test_every_label_is_reachable_for_its_own_identity(self):
        """A label the access matrix forbids is an impossible test, not a hard one.

        This is the check that caught `orion`/`13-15`/`qa_agent`: the teen band
        gets `qa_agent_limited`, and labelling it `qa_agent` would have made
        that row permanently unscorable.
        """
        for case in CASES:
            permitted = allowed_agents(
                case["persona"],
                case["age_band"],
                case["account_status"],
                user_id=case["user_id"],
            )
            assert case["expected"] in permitted, case["id"]

    def test_every_agent_the_matrix_can_grant_has_a_description(self):
        """An agent with no description is one a small model will not pick."""
        from app.graph.access import KNOWN_AGENTS

        assert KNOWN_AGENTS <= set(AGENT_DESCRIPTIONS)

    def test_the_set_covers_every_persona_and_both_identity_states(self):
        assert {case["persona"] for case in CASES} == {
            "stella",
            "orion",
            "aurora",
            "nova",
        }
        assert {case["user_id"] is None for case in CASES} == {True, False}


@pytest.mark.asyncio
class TestContainment:
    """No classifier output, however malformed or hostile, escapes the list."""

    @pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
    @pytest.mark.parametrize(
        "raw",
        [
            # A real agent, but one this caller may not reach.
            '{"agent": "servicing_agent", "confidence": 0.99, "reason": "x"}',
            '{"agent": "register_agent", "confidence": 1.0, "reason": "x"}',
            # An invented one.
            '{"agent": "root_agent", "confidence": 1.0, "reason": "x"}',
            '{"agent": "", "confidence": 1.0, "reason": "x"}',
            # Injection attempts dressed as a route.
            '{"agent": "qa_agent; DROP TABLE users", "confidence": 1.0}',
            '{"agent": "../../admin", "confidence": 1.0}',
            # Malformed, absent, or prose.
            "not json at all",
            "",
            "{",
            '{"confidence": 0.9}',
            '{"agent": null, "confidence": "high"}',
            "Sure! Here is the JSON: {\"agent\": \"qa_agent\", \"confidence\": 0.8}",
        ],
    )
    async def test_the_route_is_always_permitted(self, case, raw):
        state = state_for(case)
        if not state["allowed_agents"]:
            pytest.skip("guard would have refused this turn")
        update = await make_classify(replying(raw))(state)
        assert update["active_agent"] in state["allowed_agents"]

    @pytest.mark.parametrize("case", CASES[:8], ids=[case["id"] for case in CASES[:8]])
    async def test_a_classifier_outage_still_routes(self, case):
        """A router outage must not be a product outage."""

        async def exploding(system: str, user: str) -> str:
            raise RuntimeError("provider is down")

        update = await make_classify(exploding)(state_for(case))
        assert update["active_agent"] in state_for(case)["allowed_agents"]

    async def test_no_classifier_configured_still_routes(self):
        update = await make_classify(None)(state_for(CASES[0]))
        assert update["active_agent"] in state_for(CASES[0])["allowed_agents"]

    async def test_an_empty_allowed_list_halts_rather_than_choosing(self):
        state = state_for(CASES[0], allowed_agents=[])
        update = await make_classify(replying('{"agent":"qa_agent","confidence":1}'))(state)
        assert update["active_agent"] is None
        assert update["halt_reason"] == "access_denied"

    async def test_a_single_option_costs_no_model_call(self):
        calls: list[str] = []

        async def counting(system: str, user: str) -> str:
            calls.append(user)
            return '{"agent":"learn_agent","confidence":1}'

        state = state_for(CASES[0], allowed_agents=["learn_agent"])
        update = await make_classify(counting)(state)
        assert update["active_agent"] == "learn_agent"
        assert calls == []


class TestThePrompt:
    def test_the_menu_contains_only_permitted_agents(self):
        """The containment property, restated at the prompt boundary.

        Even if the model were perfectly obedient, it could not name an
        excluded agent -- it is never shown one.
        """
        state = state_for(CASES[0])
        menu = agent_menu(state["allowed_agents"])
        for agent in ("servicing_agent", "register_agent", "qa_agent"):
            if agent not in state["allowed_agents"]:
                assert agent not in menu

    def test_an_agent_without_a_description_is_still_listed(self):
        """Dropping it would silently make a permitted capability unreachable."""
        assert "made_up_agent" in agent_menu(["made_up_agent"])


class TestStickiness:
    def test_an_ambiguous_turn_does_not_leave_a_registration(self):
        """The case the mechanism exists for.

        A parent answering "march" mid-registration is a one-word turn with no
        registration vocabulary in it. Without stickiness the whole flow is one
        ambiguous answer away from being abandoned.
        """
        state = state_for(
            {
                "id": "s1",
                "persona": "aurora",
                "age_band": "adult",
                "account_status": "guardian",
                "user_id": "u",
                "active_agent": "register_agent",
                "utterance": "march",
            }
        )
        kept = apply_stickiness(
            Classification(agent="qa_agent", confidence=0.6, reason="date question"),
            state,
        )
        assert kept.agent == "register_agent"
        assert kept.sticky is True

    def test_a_confident_proposal_does_leave(self):
        """"I want a person" is not an ambiguous turn."""
        state = state_for(
            {
                "id": "s2",
                "persona": "aurora",
                "age_band": "adult",
                "account_status": "guardian",
                "user_id": "u",
                "active_agent": "register_agent",
                "utterance": "get me a human right now",
            }
        )
        left = apply_stickiness(
            Classification(agent="escalate_agent", confidence=0.95, reason="asked"),
            state,
        )
        assert left.agent == "escalate_agent"
        assert left.sticky is False

    def test_exactly_at_the_threshold_stays_put(self):
        """`>` not `>=`, because small models emit 0.75 for everything."""
        state = state_for(
            {
                "id": "s3",
                "persona": "aurora",
                "age_band": "adult",
                "account_status": "guardian",
                "user_id": "u",
                "active_agent": "register_agent",
                "utterance": "hm",
            }
        )
        held = apply_stickiness(
            Classification(agent="qa_agent", confidence=0.75), state
        )
        assert held.agent == "register_agent"

    def test_stickiness_does_not_resurrect_a_now_forbidden_agent(self):
        """A band change between turns must not be overridden by history."""
        state = state_for(
            {
                "id": "s4",
                "persona": "stella",
                "age_band": "5-8",
                "account_status": "beneficiary",
                "user_id": "u",
                "active_agent": "register_agent",
                "utterance": "carry on",
            }
        )
        assert "register_agent" not in state["allowed_agents"]
        result = apply_stickiness(
            Classification(agent="learn_agent", confidence=0.1), state
        )
        assert result.agent == "learn_agent"

    def test_no_active_agent_means_no_stickiness(self):
        state = state_for(CASES[0])
        result = apply_stickiness(
            Classification(agent="escalate_agent", confidence=0.1), state
        )
        assert result.agent == "escalate_agent"


# ── accuracy, against a real model ───────────────────────────────────────────

ACCURACY_TARGET = 0.85


def _model_available() -> bool:
    """Whether the model the router would actually use is callable here.

    Goes through `resolve_classifier_model` rather than reading the setting, so
    a deployment that falls back to its chat model still runs this measurement
    rather than skipping it and reporting nothing.
    """
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
@pytest.mark.skipif(
    not _model_available(), reason="no API key for the configured classifier model"
)
async def test_routing_accuracy_against_the_labelled_set(capsys):
    """Reports accuracy, and fails below the target.

    Reported rather than merely asserted: the number is the point. A run that
    passes at 86% and a run that passes at 97% are very different states of the
    prompt, and only one of them is worth leaving alone.
    """
    from app.graph.nodes.classify import default_invoke

    classify = make_classify(default_invoke)
    correct = 0
    wrong: list[str] = []

    for case in CASES:
        state = state_for(case)
        update = await classify(state)
        chosen = update["active_agent"]
        assert chosen in state["allowed_agents"], case["id"]
        if chosen == case["expected"]:
            correct += 1
        else:
            wrong.append(f"{case['id']}: {case['utterance']!r} -> {chosen} (want {case['expected']})")

    accuracy = correct / len(CASES)
    with capsys.disabled():
        print(f"\nrouting accuracy: {accuracy:.1%} ({correct}/{len(CASES)})")
        for line in wrong:
            print(f"  miss  {line}")

    assert accuracy > ACCURACY_TARGET, f"{accuracy:.1%} is below {ACCURACY_TARGET:.0%}"
