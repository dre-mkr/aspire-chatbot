"""The access matrix, walked exhaustively.

There are 4 personas x 5 bands x 4 account statuses x 2 identity states = 160
combinations, and this file evaluates all of them. That is not thoroughness for
its own sake: the matrix is an authorisation control on a product used by
children, the combination space is small enough to enumerate, and "we tested the
interesting cases" is exactly how the uninteresting case that matters gets
missed.

The four properties the specification names are each asserted over the full
space rather than over a hand-picked example, so a future edit that widens a row
fails here rather than in production.
"""

from __future__ import annotations

import itertools

import pytest

from app.graph.access import (
    ACCOUNT_STATUSES,
    AGE_BANDS,
    KNOWN_AGENTS,
    PERSONAS,
    allowed_agents,
    is_denied,
)

#: Sorted so the parametrised ids are stable between runs. An unstable id makes
#: `pytest --lf` useless and makes a CI failure impossible to correlate.
ALL_PERSONAS = sorted(PERSONAS)
ALL_BANDS = sorted(AGE_BANDS)
ALL_STATUSES = sorted(ACCOUNT_STATUSES)

#: Every authenticated combination. `user_id` is a real-looking string because
#: the function checks `is None` and nothing else -- passing "" would test a
#: falsy-but-present id, which is a different (and also correct) case covered
#: separately below.
SIGNED_IN = list(itertools.product(ALL_PERSONAS, ALL_BANDS, ALL_STATUSES))

USER = "9f1c2b4e-0000-4000-8000-000000000001"


@pytest.mark.parametrize(("persona", "band", "status"), SIGNED_IN)
class TestEveryAuthenticatedCombination:
    """Properties that must hold for all 80 signed-in combinations."""

    def test_only_known_agents_are_ever_returned(self, persona, band, status):
        """No combination invents an agent.

        The failure this catches is a typo in a row: `"servicing_agnet"` does
        not raise anywhere, it simply becomes an agent the router will never
        match, so the capability silently disappears for whoever that row
        serves.
        """
        agents = allowed_agents(persona, band, status, user_id=USER)
        unknown = set(agents) - KNOWN_AGENTS
        assert not unknown, f"{persona}/{band}/{status} produced {unknown}"

    def test_no_duplicates(self, persona, band, status):
        """A repeated agent would double-count in any budget built on this."""
        agents = allowed_agents(persona, band, status, user_id=USER)
        assert len(agents) == len(set(agents))

    def test_escalation_is_always_available_or_nothing_is(self, persona, band, status):
        """Every covered combination can reach a human.

        A row that grants agents but no route out is the one shape of this
        table that would be actively harmful: a child in distress, held by an
        agent that cannot hand them on.
        """
        agents = allowed_agents(persona, band, status, user_id=USER)
        assert is_denied(agents) or "escalate_agent" in agents

    def test_stella_never_reaches_registration_servicing_or_full_qa(
        self, persona, band, status
    ):
        """Stella is the six-year-old's mascot. Three agents she may never have.

        `register_agent` collects a national ID and a date of birth;
        `servicing_agent` moves money; `qa_agent` is the unfiltered corpus. None
        of the three is something a child should be able to reach by typing.
        """
        if persona != "stella":
            return
        agents = set(allowed_agents(persona, band, status, user_id=USER))
        assert not agents & {"register_agent", "servicing_agent", "qa_agent"}

    def test_orion_under_sixteen_never_reaches_registration(
        self, persona, band, status
    ):
        """Under-16 Orion cannot register, in any account status.

        Note this asserts over *every* band Orion can hold rather than over
        "13-15" alone, so a future row for `orion`/`9-12` that quietly included
        registration fails here.
        """
        if persona != "orion" or band in ("16-18", "adult"):
            return
        agents = allowed_agents(persona, band, status, user_id=USER)
        assert "register_agent" not in agents


class TestAnonymous:
    """The unauthenticated row, and the fact that it wins."""

    @pytest.mark.parametrize(("persona", "band", "status"), SIGNED_IN)
    def test_anonymous_overrides_every_persona_and_band(self, persona, band, status):
        """A claimed persona changes nothing without a proven identity.

        Persona is chosen in the UI. Treating it as a permission input for a
        caller who has not signed in would mean the permission is chosen in the
        UI too.
        """
        assert allowed_agents(persona, band, status, user_id=None) == [
            "qa_agent_public",
            "learning_sample",
            "register_agent_step1",
            "escalate_agent",
        ]

    @pytest.mark.parametrize(("persona", "band", "status"), SIGNED_IN)
    def test_anonymous_never_reaches_servicing(self, persona, band, status):
        assert "servicing_agent" not in allowed_agents(
            persona, band, status, user_id=None
        )

    def test_anonymous_tolerates_nonsense_claims(self):
        """A broken client is not an attacker.

        An unauthenticated caller has no verified claims to validate, so
        refusing them the public Q&A because their persona string is garbage
        would punish the wrong party. They get the anonymous row regardless.
        """
        assert allowed_agents("root", "-1", "superuser", user_id=None) == list(
            allowed_agents("stella", "5-8", "prospect", user_id=None)
        )

    def test_an_empty_string_user_id_is_not_anonymous(self):
        """`""` is a present identity, however implausible.

        Asserted because the check is `is None` and it would be easy to
        "improve" it into a truthiness test -- which would silently downgrade
        any caller whose id serialised to an empty string to the public row.
        """
        assert allowed_agents("aurora", "adult", "guardian", user_id="") != list(
            allowed_agents("aurora", "adult", "guardian", user_id=None)
        )


class TestTheRowsThemselves:
    """Each row, stated once, exactly."""

    @pytest.mark.parametrize("band", ALL_BANDS)
    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_stella_in_every_band(self, band, status):
        assert allowed_agents("stella", band, status, user_id=USER) == [
            "learn_agent",
            "escalate_agent",
        ]

    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_orion_thirteen_to_fifteen(self, status):
        assert allowed_agents("orion", "13-15", status, user_id=USER) == [
            "learn_agent",
            "qa_agent_limited",
            "escalate_agent",
        ]

    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_orion_sixteen_to_eighteen(self, status):
        assert allowed_agents("orion", "16-18", status, user_id=USER) == [
            "learn_agent",
            "qa_agent",
            "register_agent",
            "servicing_agent",
            "escalate_agent",
        ]

    @pytest.mark.parametrize("band", ["5-8", "9-12", "adult"])
    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_orion_outside_his_bands_is_refused(self, band, status):
        """Orion is the teen mascot; those three bands are not his.

        A token asserting one is stale or forged. This is not the place to work
        out which -- it is the place to serve nothing.
        """
        assert allowed_agents("orion", band, status, user_id=USER) == []

    @pytest.mark.parametrize("band", ALL_BANDS)
    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_aurora(self, band, status):
        assert allowed_agents("aurora", band, status, user_id=USER) == [
            "qa_agent",
            "register_agent",
            "servicing_agent",
            "escalate_agent",
            "learning_preview",
        ]

    @pytest.mark.parametrize("band", ALL_BANDS)
    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_nova(self, band, status):
        assert allowed_agents("nova", band, status, user_id=USER) == [
            "qa_agent",
            "register_agent",
            "escalate_agent",
        ]


class TestUnknownCombinations:
    """Anything outside the closed vocabularies is refused, one axis at a time."""

    @pytest.mark.parametrize(
        "persona", ["", "root", "STELLA", "stella ", "admin", "learn_agent"]
    )
    def test_an_unknown_persona_is_refused(self, persona):
        assert allowed_agents(persona, "adult", "guardian", user_id=USER) == []

    @pytest.mark.parametrize("band", ["", "0-4", "19+", "5-8 ", "ADULT", "13"])
    def test_an_unknown_band_is_refused(self, band):
        assert allowed_agents("aurora", band, "guardian", user_id=USER) == []

    @pytest.mark.parametrize("status", ["", "admin", "PROSPECT", "staff", "customer"])
    def test_an_unknown_account_status_is_refused(self, status):
        """Account status is currently unused by every row, and still validated.

        That is deliberate. The moment a row varies by status, an unvalidated
        value would fall through to whichever row was written last. Refusing it
        now means adding that row later cannot open a hole.
        """
        assert allowed_agents("aurora", "adult", status, user_id=USER) == []

    def test_refusal_is_reported_as_a_refusal(self):
        assert is_denied(allowed_agents("orion", "5-8", "prospect", user_id=USER))
        assert not is_denied(allowed_agents("nova", "adult", "prospect", user_id=USER))


class TestPurity:
    """The properties that come from being a pure function, asserted as such."""

    def test_the_result_is_not_shared_between_calls(self):
        """A caller mutating its list must not edit the matrix.

        The rows are module-level tuples and each call copies. Without the copy,
        one caller doing `agents.remove("escalate_agent")` would remove it for
        every subsequent caller in the process -- a permission change with no
        code change and no log line.
        """
        first = allowed_agents("aurora", "adult", "guardian", user_id=USER)
        first.append("root_agent")
        second = allowed_agents("aurora", "adult", "guardian", user_id=USER)
        assert "root_agent" not in second

    @pytest.mark.parametrize(("persona", "band", "status"), SIGNED_IN)
    def test_repeated_calls_agree(self, persona, band, status):
        """No clock, no environment, no I/O. Same input, same answer, always."""
        first = allowed_agents(persona, band, status, user_id=USER)
        second = allowed_agents(persona, band, status, user_id=USER)
        assert first == second

    def test_no_row_is_reachable_that_is_not_in_the_known_set(self):
        """The union of every row is exactly `KNOWN_AGENTS`.

        Both directions matter. An agent in a row and not in the set is caught
        by the per-combination test above; an agent in the set and in no row is
        caught here, and means either a row was dropped or the set has a name
        nothing can ever grant.
        """
        granted: set[str] = set()
        for persona, band, status in SIGNED_IN:
            granted.update(allowed_agents(persona, band, status, user_id=USER))
        granted.update(allowed_agents("stella", "5-8", "prospect", user_id=None))
        assert granted == KNOWN_AGENTS
