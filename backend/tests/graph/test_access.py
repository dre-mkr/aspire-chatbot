"""The access matrix, walked exhaustively."""

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

#: Sorted so the parametrised ids are stable between runs.
ALL_PERSONAS = sorted(PERSONAS)
ALL_BANDS = sorted(AGE_BANDS)
ALL_STATUSES = sorted(ACCOUNT_STATUSES)

#: Every authenticated combination.
SIGNED_IN = list(itertools.product(ALL_PERSONAS, ALL_BANDS, ALL_STATUSES))

USER = "9f1c2b4e-0000-4000-8000-000000000001"


@pytest.mark.parametrize(("persona", "band", "status"), SIGNED_IN)
class TestEveryAuthenticatedCombination:
    """Properties that must hold for all 80 signed-in combinations."""

    def test_only_known_agents_are_ever_returned(self, persona, band, status):
        """No combination invents an agent."""
        agents = allowed_agents(persona, band, status, user_id=USER)
        unknown = set(agents) - KNOWN_AGENTS
        assert not unknown, f"{persona}/{band}/{status} produced {unknown}"

    def test_no_duplicates(self, persona, band, status):
        """A repeated agent would double-count in any budget built on this."""
        agents = allowed_agents(persona, band, status, user_id=USER)
        assert len(agents) == len(set(agents))

    def test_escalation_is_always_available_or_nothing_is(self, persona, band, status):
        """Every covered combination can reach a human."""
        agents = allowed_agents(persona, band, status, user_id=USER)
        assert is_denied(agents) or "escalate_agent" in agents

    def test_stella_never_reaches_registration_servicing_or_full_qa(
        self, persona, band, status
    ):
        """Stella is the six-year-old's mascot."""
        if persona != "stella":
            return
        agents = set(allowed_agents(persona, band, status, user_id=USER))
        assert not agents & {"register_agent", "servicing_agent", "qa_agent"}

    def test_only_a_guardian_reaches_registration(self, persona, band, status):
        """`register_agent` belongs to `aurora` and to nobody else."""
        agents = allowed_agents(persona, band, status, user_id=USER)
        if "register_agent" in agents:
            assert persona == "aurora"

    def test_a_signed_out_visitor_reaches_only_step_one(self, persona, band, status):
        """Step 1 is not registration, and the distinction is load-bearing."""
        agents = allowed_agents(persona, band, status, user_id=None)
        assert "register_agent" not in agents
        assert "register_agent_step1" in agents


class TestAnonymous:
    """The unauthenticated row, and the fact that it wins."""

    @pytest.mark.parametrize(("persona", "band", "status"), SIGNED_IN)
    def test_anonymous_overrides_every_persona_and_band(self, persona, band, status):
        """A claimed persona changes nothing without a proven identity."""
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
        """A broken client is not an attacker."""
        assert allowed_agents("root", "-1", "superuser", user_id=None) == list(
            allowed_agents("stella", "5-8", "prospect", user_id=None)
        )

    def test_an_empty_string_user_id_is_not_anonymous(self):
        """`""` is a present identity, however implausible."""
        assert allowed_agents("aurora", "adult", "guardian", user_id="") != list(
            allowed_agents("aurora", "adult", "guardian", user_id=None)
        )


class TestTheRowsThemselves:
    """Each row, stated once, exactly."""

    @pytest.mark.parametrize("band", ["5-8", "9-12"])
    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_stella_in_her_own_bands(self, band, status):
        # Q&A leads: row order is what makes `classify`'s fallback pick it.
        assert allowed_agents("stella", band, status, user_id=USER) == [
            "qa_agent_limited",
            "learn_agent",
            "escalate_agent",
        ]

    @pytest.mark.parametrize("band", ["13-15", "16-18", "adult"])
    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_stella_outside_her_bands_is_refused(self, band, status):
        """Stella is a child's persona and is bounded by a child's bands."""
        assert allowed_agents("stella", band, status, user_id=USER) == []

    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_orion_thirteen_to_fifteen(self, status):
        assert allowed_agents("orion", "13-15", status, user_id=USER) == [
            "qa_agent_limited",
            "learn_agent",
            "escalate_agent",
        ]

    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_orion_sixteen_to_eighteen(self, status):
        """Old enough to hold an account, not to be the person who opens one."""
        assert allowed_agents("orion", "16-18", status, user_id=USER) == [
            "qa_agent",
            "learn_agent",
            "servicing_agent",
            "escalate_agent",
        ]

    @pytest.mark.parametrize("band", ["5-8", "9-12", "adult"])
    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_orion_outside_his_bands_is_refused(self, band, status):
        """Orion is the teen mascot; those three bands are not his."""
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
        """Teaching yes; servicing and registration no.

        The exclusion this docstring always named -- servicing and registration
        both act on another person's account -- is unchanged and is the whole
        of it. What used to sit alongside it was the ABSENCE of any teaching
        agent, which nothing argued for: the teacher persona could neither
        teach nor be taught, while `aurora`, a parent, held `learning_preview`
        and could see the lessons Azuri delivers.

        A teacher has the stronger claim on the preview -- the guardian is
        curious about the lesson, the teacher is delivering it -- and on the
        tutor, because working out how compounding lands before standing in
        front of Form 3 is the ordinary case.
        """
        assert allowed_agents("nova", band, status, user_id=USER) == [
            "qa_agent",
            "learning_preview",
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
        """Account status is currently unused by every row, and still validated."""
        assert allowed_agents("aurora", "adult", status, user_id=USER) == []

    def test_refusal_is_reported_as_a_refusal(self):
        assert is_denied(allowed_agents("orion", "5-8", "prospect", user_id=USER))
        assert not is_denied(allowed_agents("nova", "adult", "prospect", user_id=USER))


class TestPurity:
    """The properties that come from being a pure function, asserted as such."""

    def test_the_result_is_not_shared_between_calls(self):
        """A caller mutating its list must not edit the matrix."""
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
        """The union of every row is exactly `KNOWN_AGENTS`."""
        granted: set[str] = set()
        for persona, band, status in SIGNED_IN:
            granted.update(allowed_agents(persona, band, status, user_id=USER))
        granted.update(allowed_agents("stella", "5-8", "prospect", user_id=None))
        assert granted == KNOWN_AGENTS


class TestAnUnprovenIdentityIsAVisitor:
    """A signed-out visitor is given an anonymous account row so their chats survive
    sign-up. `guard` used to read that row's id as proof of who they were, and the
    row's empty date of birth derives `aurora/adult` -- so a visitor was handed the
    guardian row, `register_agent` (the variant that collects a national id) included.
    """

    @staticmethod
    def _state(**overrides):
        return {
            "persona": "aurora",
            "age_band": "adult",
            "account_status": "prospect",
            # Present, because the chats have to belong to something.
            "user_id": "0f8e0f57-0000-4000-8000-000000000000",
            "identity_proven": False,
            "locale": "en",
            **overrides,
        }

    def _agents(self, **overrides):
        from app.graph.nodes.guard import guard

        return guard(self._state(**overrides)).get("allowed_agents")

    def test_a_visitor_gets_the_visitor_row(self):
        assert self._agents() == [
            "qa_agent_public",
            "learning_sample",
            "register_agent_step1",
            "escalate_agent",
        ]

    def test_a_visitor_never_reaches_the_sensitive_registration_agent(self):
        """`register_agent_step1` exists to stop before the sensitive slots."""
        assert "register_agent" not in self._agents()

    def test_a_visitor_never_reaches_a_guardians_view_of_a_child(self):
        assert "learning_preview" not in self._agents()

    def test_proving_who_you_are_restores_the_guardian_row(self):
        assert "register_agent" in self._agents(identity_proven=True)

    def test_a_token_minted_before_the_claim_existed_is_still_a_member(self):
        """Absent means proven: only a signed-in member's token outlives a reload."""
        state = self._state()
        del state["identity_proven"]
        from app.graph.nodes.guard import guard

        assert "register_agent" in guard(state)["allowed_agents"]

    def test_the_visitor_row_does_not_depend_on_the_persona_the_row_derived(self):
        assert self._agents(persona="stella", age_band="5-8") == self._agents()


class TestEveryoneNeverWidens:
    """`everyone` is a voice, and a voice must not be a way to reach more.

    It is the persona a reader gets by picking "Everyone" in the composer, which
    is also the option a stranger reaches by editing a URL. So the property that
    matters is not which agents it grants but that it grants nothing new: every
    result is a set the caller's own band already had.
    """

    #: Every persona that can really hold each band. `guest` must be a subset
    #: of ALL of them, which is the property the class docstring states.
    PERSONAS_AT_BAND = {
        "5-8": ("stella",),
        "9-12": ("kaleb",),
        "13-15": ("orion",),
        "16-18": ("orion",),
        "adult": ("aurora", "nova"),
    }

    @pytest.mark.parametrize("band", ALL_BANDS)
    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_it_grants_nothing_the_band_did_not_already_have(self, band, status):
        """The property, as the docstring states it.

        This replaced an equality check against a single "default persona for
        the band", which was a STRONGER claim than the class ever argued for and
        was true only by accident: `guest` at `adult` returned `list(_NOVA)`, so
        it matched Azuri's row because it WAS Azuri's row. Widening Azuri
        widened guest with it -- the escalation this class exists to stop --
        and the equality is what surfaced it.

        Its lookup table had also drifted from the app in two places: it said
        `9-12 -> stella` where `DEFAULT_PERSONA` says `kaleb`, and
        `adult -> nova` where it says `aurora`. Repairing the table would have
        kept a claim the class does not make; asserting the subset against every
        persona that can hold the band is what it does make, and it is stricter
        for the adult band, which has two.
        """
        theirs = set(allowed_agents("guest", band, status, user_id=USER))
        for persona in self.PERSONAS_AT_BAND[band]:
            row = set(allowed_agents(persona, band, status, user_id=USER))
            assert theirs <= row, (
                f"guest/{band} reaches {sorted(theirs - row)}, which "
                f"{persona}/{band} does not grant"
            )

    def test_the_adult_visitor_row_is_its_own_thing(self):
        """Named, so the reuse cannot come back by accident.

        `guest` at `adult` is factual answers and a way to reach a person. Not
        registration, which is Aurora's; not teaching, which needs a band this
        reader has not given.
        """
        assert allowed_agents("guest", "adult", "prospect", user_id=USER) == [
            "qa_agent",
            "escalate_agent",
        ]

    @pytest.mark.parametrize("band", ALL_BANDS)
    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_it_is_never_denied_outright(self, band, status):
        """Unlike stella and orion, it has no band of its own to fall outside of."""
        assert not is_denied(allowed_agents("guest", band, status, user_id=USER))

    @pytest.mark.parametrize("band", ALL_BANDS)
    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_it_never_reaches_registration(self, band, status):
        """Opening an application on a child's behalf stays Aurora's alone."""
        assert "register_agent" not in allowed_agents(
            "guest", band, status, user_id=USER
        )

    @pytest.mark.parametrize("band", ALL_BANDS)
    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_a_child_band_keeps_the_band_filtered_corpus(self, band, status):
        """Picking a general voice must not hand a nine-year-old the adult agent."""
        agents = allowed_agents("guest", band, status, user_id=USER)
        if band in {"5-8", "9-12", "13-15"}:
            assert "qa_agent" not in agents
            assert "qa_agent_limited" in agents

    #: The persona/band pairs an account can actually derive, from
    #: `account.DEFAULT_PERSONA` and `account.ROLE_PERSONA`.
    REAL_PAIRS = [
        ("stella", "5-8"),
        ("kaleb", "9-12"),
        ("orion", "13-15"),
        ("orion", "16-18"),
        ("aurora", "adult"),
        ("nova", "adult"),
    ]

    @pytest.mark.parametrize(("persona", "band"), REAL_PAIRS)
    @pytest.mark.parametrize("status", ALL_STATUSES)
    def test_it_is_grantable_from_every_account_that_can_exist(self, persona, band, status):
        """`_narrowing` admits a requested persona only if it is a subset.

        This is what makes "Everyone" selectable from any account rather than
        silently refused for some of them. Only pairs an account can really
        derive are checked: `aurora` at `5-8` is not a reachable state, and
        asserting over the full cross product tests arithmetic, not the product.
        """
        theirs = set(allowed_agents("guest", band, status, user_id=USER))
        row = set(allowed_agents(persona, band, status, user_id=USER))
        assert theirs <= row, f"everyone/{band} is not a subset of {persona}/{band}"
