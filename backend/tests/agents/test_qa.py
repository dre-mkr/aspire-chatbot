"""The Q&A subgraph: retrieval, grounding, and the tools that do the arithmetic."""

from __future__ import annotations

import os
from datetime import date

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from app.agents.qa import nodes  # noqa: E402
from app.agents.qa import tools  # noqa: E402
from app.agents.qa.graph import build_qa_graph  # noqa: E402
from app.graph.state import KBChunk, initial_state  # noqa: E402

CORPUS: list[tuple[str, str]] = [
    ("ASP-001", "ASPIRE is open to children aged 5 to 18 who are citizens or residents."),
    ("ASP-002", "A parent or legal guardian must open the account on the child's behalf."),
    ("ASP-003", "The minimum opening deposit is EC$25."),
    ("ASP-004", "Applications close on 31 March each year."),
    ("ASP-005", "Bring the child's birth certificate and the guardian's photo ID."),
    ("ASP-006", "The Basseterre branch is on Central Street and opens at 8am."),
    ("ASP-007", "Interest is credited to ASPIRE accounts twice a year."),
]


def chunks_for(*ids: str, score: float = 0.9, relevance: float | None = None) -> list[KBChunk]:
    """Chunks as the dense retriever would produce them."""
    lookup = dict(CORPUS)
    return [
        KBChunk(
            kb_id=i,
            content=lookup[i],
            score=score,
            relevance=score if relevance is None else relevance,
        )
        for i in ids
    ]


def state_for(question: str, **overrides):
    state = initial_state(
        session_id="s-qa",
        user_id="u-qa",
        device_id="d",
        persona=overrides.pop("persona", "aurora"),
        age_band=overrides.pop("age_band", "adult"),
        account_status="guardian",
    )
    state["messages"] = [HumanMessage(content=question)]
    state["active_agent"] = overrides.pop("active_agent", "qa_agent")
    state.update(overrides)
    return state


async def corpus(audience: str = "all"):
    return CORPUS


def dense_returning(*ids: str):
    async def search(query: str, k: int):
        return chunks_for(*ids)

    return search


def generating(text: str):
    async def invoke(messages):
        return text

    return invoke


# ── retrieval ────────────────────────────────────────────────────────────────


class TestHybridRetrieval:
    @pytest.mark.asyncio
    async def test_bm25_finds_an_exact_term_the_dense_side_missed(self):
        """The reason both halves exist."""
        node = nodes.make_hybrid_retrieve(dense_returning("ASP-001"), corpus)
        result = await node(state_for("what does ASP-004 say"))
        assert "ASP-004" in {chunk.kb_id for chunk in result["retrieved"]}

    @pytest.mark.asyncio
    async def test_the_dense_side_carries_a_question_with_no_shared_words(self):
        node = nodes.make_hybrid_retrieve(dense_returning("ASP-002"), corpus)
        result = await node(state_for("who signs the paperwork for a youngster"))
        assert "ASP-002" in {chunk.kb_id for chunk in result["retrieved"]}

    @pytest.mark.asyncio
    async def test_a_dense_failure_does_not_fail_the_turn(self):
        """Survivable precisely BECAUSE there is a second retriever."""

        async def broken(query, k):
            raise RuntimeError("pgvector is down")

        node = nodes.make_hybrid_retrieve(broken, corpus)
        result = await node(state_for("what is the minimum deposit"))
        assert result["retrieved"]

    def test_rrf_uses_ranks_and_not_scores(self):
        """Agreement near the top wins, without either score being comparable."""
        fused = nodes.rrf_fuse([["a", "b", "c"], ["c", "a", "b"]], k=60)
        assert fused["a"] > fused["c"] > fused["b"]

    def test_rrf_of_an_empty_ranking_is_harmless(self):
        assert nodes.rrf_fuse([[], ["a"]])["a"] > 0

    def test_the_tokeniser_keeps_currency_together(self):
        """Dropping `$` splits "EC$500" into "ec" and "500"."""
        assert "ec$25" in nodes._tokens("The minimum is EC$25 today")


class TestAudienceFilter:
    """`qa_agent_limited` and `qa_agent_public` are the same graph with a filter."""

    @pytest.mark.parametrize(
        ("agent", "audience"),
        [
            ("qa_agent", "all"),
            ("qa_agent_limited", "youth"),
            ("qa_agent_public", "public"),
        ],
    )
    def test_the_agent_name_selects_the_slice(self, agent, audience):
        assert nodes._audience(state_for("x", active_agent=agent)) == audience

    def test_an_untagged_row_is_visible_to_everyone(self):
        """Defaulting to hidden would empty the corpus for two agents on the day the tags were added."""
        chunk = KBChunk(kb_id="ASP-001", content="x")
        assert nodes._permitted(chunk, "public")
        assert nodes._permitted(chunk, "youth")

    def test_a_staff_only_row_is_hidden_from_the_public_agent(self):
        chunk = KBChunk(kb_id="ASP-009", content="x", metadata={"audience": ["staff"]})
        assert not nodes._permitted(chunk, "public")
        assert nodes._permitted(chunk, "all")

    @pytest.mark.parametrize(
        "tag", ["general", "student", "child", "parent", "teacher"]
    )
    def test_the_corpus_vocabulary_reaches_the_filtered_agents(self, tag: str):
        """The regression, and it was a total one."""
        chunk = KBChunk(kb_id="ASP-001", content="x", metadata={"audience": tag})
        assert nodes._permitted(chunk, "public"), f"{tag!r} is invisible to the public agent"
        assert nodes._permitted(chunk, "youth"), f"{tag!r} is invisible to the youth agent"

    @pytest.mark.parametrize("tag", ["staff", "internal", "reviewer_only"])
    def test_a_tier_the_corpus_does_not_publish_is_barred(self, tag: str):
        """What the filter is actually for, now and later."""
        chunk = KBChunk(kb_id="ASP-500", content="x", metadata={"audience": tag})
        assert not nodes._permitted(chunk, "public")
        assert not nodes._permitted(chunk, "youth")
        assert nodes._permitted(chunk, "all")

    def test_tags_are_matched_case_and_space_insensitively(self):
        """The tags come from a hand-maintained CSV column."""
        chunk = KBChunk(kb_id="ASP-002", content="x", metadata={"audience": " Student "})
        assert nodes._permitted(chunk, "public")


# ── grounding ────────────────────────────────────────────────────────────────


def assert_declined(command, gate: str) -> None:
    """The gate fired and the turn was not answered."""
    assert not command.goto, f"{gate} should decline on the first attempt, not escalate"
    declined = (command.update or {}).get("safety_flags", {}).get("declined")
    assert declined, "a declined turn must record which gate declined it"
    assert declined["reason"] == gate, f"expected gate {gate}, got {declined['reason']}"
    assert command.update["messages"][0].content, "a decline must say something"
    assert command.update["citations"] == []


class TestGroundCheck:
    @pytest.mark.asyncio
    async def test_a_grounded_answer_carries_citations_to_row_ids(self):
        """The acceptance criterion, stated directly."""
        state = state_for("what is the minimum deposit")
        state["retrieved"] = chunks_for("ASP-003", "ASP-001")
        state["messages"].append(
            AIMessage(content="The minimum opening deposit is EC$25 [ASP-003].")
        )

        command = await nodes.make_ground_check()(state)

        assert command.goto in ((), [], None, "__end__") or not command.goto
        assert [c.kb_id for c in command.update["citations"]] == ["ASP-003"]
        assert command.update["groundedness"] > 0

    @pytest.mark.asyncio
    async def test_an_out_of_kb_question_escalates_rather_than_answering(self):
        """The acceptance criterion. Nothing retrieved means nothing to answer from."""
        state = state_for("what is the capital of Mongolia")
        state["retrieved"] = []
        state["messages"].append(AIMessage(content="Ulaanbaatar."))

        command = await nodes.make_ground_check()(state)

        assert_declined(command, "no_context")

    @pytest.mark.asyncio
    async def test_a_weak_best_chunk_escalates(self):
        state = state_for("something tangential")
        state["retrieved"] = chunks_for("ASP-006", score=0.05)
        state["messages"].append(AIMessage(content="Probably [ASP-006]."))
        command = await nodes.make_ground_check()(state)
        assert_declined(command, "below_relevance_floor")

    @pytest.mark.asyncio
    async def test_an_invented_figure_escalates(self):
        """The failure RAG systems actually have."""
        state = state_for("what is the minimum deposit")
        # The right chunk WAS retrieved -- coverage is total, so the relevance gate passes and this test is about the a…
        state["retrieved"] = chunks_for("ASP-003")
        state["messages"].append(
            AIMessage(content="The minimum opening deposit is EC$500 [ASP-003].")
        )

        command = await nodes.make_ground_check()(state)

        assert_declined(command, "unattributed_figure")

    @pytest.mark.asyncio
    async def test_a_question_the_corpus_has_never_heard_of_escalates_on_coverage(self):
        """The gate a rank-fusion score cannot provide."""
        state = state_for("how do I renew a fishing licence")
        # BM25-only: the dense side saw nothing, so the lexical floor is what has to catch this.
        state["retrieved"] = chunks_for("ASP-006", "ASP-007", relevance=0.0)
        state["messages"].append(AIMessage(content="At the fisheries office [ASP-006]."))

        command = await nodes.make_ground_check()(state)

        assert_declined(command, "below_relevance_floor")

    @pytest.mark.asyncio
    async def test_the_coverage_gate_does_not_fire_on_a_translated_question(self):
        """The corpus is English and cross-lingual retrieval is deliberate."""
        state = state_for("quel est le dépôt minimum", locale="fr")
        state["retrieved"] = chunks_for("ASP-003")
        state["messages"].append(
            AIMessage(content="Le dépôt minimum est de EC$25 [ASP-003].")
        )
        command = await nodes.make_ground_check()(state)
        assert command.goto != "escalate_agent"

    def test_coverage_ignores_function_words(self):
        chunks = chunks_for("ASP-003")
        assert nodes.lexical_coverage("what is the minimum deposit", chunks) == 1.0
        assert nodes.lexical_coverage("capital of Mongolia", chunks) == 0.0

    def test_a_query_with_no_content_words_is_not_blamed_here(self):
        """"what is it?" is a rewrite failure, not a retrieval failure."""
        assert nodes.lexical_coverage("what is it", chunks_for("ASP-003")) == 1.0

    @pytest.mark.asyncio
    async def test_a_figure_that_is_in_a_chunk_is_fine_in_any_format(self):
        """`EC$25.00` and `25` are the same number."""
        state = state_for("deposit")
        state["retrieved"] = chunks_for("ASP-003")
        state["messages"].append(AIMessage(content="It is EC$25.00 [ASP-003]."))
        command = await nodes.make_ground_check()(state)
        assert command.goto != "escalate_agent"

    @pytest.mark.asyncio
    async def test_a_policy_claim_with_no_citation_escalates(self):
        state = state_for("can my nephew join")
        state["retrieved"] = chunks_for("ASP-001")
        state["messages"].append(
            AIMessage(content="A nephew is eligible and must be enrolled by you.")
        )
        command = await nodes.make_ground_check()(state)
        assert_declined(command, "uncited")

    @pytest.mark.asyncio
    async def test_the_escalation_summary_is_redacted(self):
        """The summary only exists once the third attempt earns a person, so the redaction has to be asserted there."""
        from app.agents.escalation import counter

        node = nodes.make_ground_check()
        streak: dict = {}
        for _ in range(counter.LIMIT - 1):
            state = state_for("my id is A12345678, am I eligible")
            state["retrieved"] = []
            state["messages"].append(AIMessage(content="Yes."))
            state["decline_streak"] = streak
            command = await node(state)
            streak = command.update["decline_streak"]
            assert "A12345678" not in command.update["messages"][0].content

        state = state_for("my id is A12345678, am I eligible")
        state["retrieved"] = []
        state["messages"].append(AIMessage(content="Yes."))
        state["decline_streak"] = streak
        command = await node(state)

        assert command.goto == "escalate_agent"
        assert "A12345678" not in command.update["escalation_summary"]

    @pytest.mark.parametrize(
        ("raw", "normalised"),
        [
            ("EC$1,200.00", "1200"),
            ("$25", "25"),
            ("25", "25"),
            ("5%", "5"),
            ("0", "0"),
            ("007", "7"),
        ],
    )
    def test_figure_normalisation(self, raw, normalised):
        assert nodes.normalise_figure(raw) == normalised

    def test_small_ordinals_are_not_treated_as_claims(self):
        """"three documents" and "step 2" are not figures somebody acts on."""
        assert nodes.unattributed_figures("Bring 3 documents in step 2.", chunks_for("ASP-005")) == []


# ── the whole subgraph ───────────────────────────────────────────────────────


class TestTheSubgraph:
    @pytest.mark.asyncio
    async def test_a_grounded_question_runs_end_to_end(self):
        graph = build_qa_graph(
            search=dense_returning("ASP-003"),
            corpus=corpus,
            generate_invoke=generating("The minimum opening deposit is EC$25 [ASP-003]."),
        )
        result = await graph.ainvoke(state_for("what is the minimum deposit"))
        assert [c.kb_id for c in result["citations"]] == ["ASP-003"]
        assert result["groundedness"] > 0

    @pytest.mark.asyncio
    async def test_the_opening_turn_skips_the_rewrite_model_call(self):
        """An opening question has no context to resolve, so the call is waste."""
        calls: list[str] = []

        async def rewrite(system, user):
            calls.append(user)
            return "rewritten"

        node = nodes.make_rewrite_query(rewrite)
        result = await node(state_for("who can apply"))
        assert calls == []
        assert result["qa_query"] == "who can apply"

    @pytest.mark.asyncio
    async def test_a_mid_conversation_pronoun_is_resolved(self):
        async def rewrite(system, user):
            return "what are the eligibility rules for a son"

        state = state_for("and for my son?")
        state["messages"] = [
            HumanMessage(content="who can apply"),
            AIMessage(content="Children aged 5 to 18 [ASP-001]."),
            HumanMessage(content="and for my son?"),
        ]
        result = await nodes.make_rewrite_query(rewrite)(state)
        assert result["qa_query"] == "what are the eligibility rules for a son"

    @pytest.mark.asyncio
    async def test_a_runaway_rewrite_falls_back_to_the_question(self):
        async def rewrite(system, user):
            return "x" * 5000

        state = state_for("and my son?")
        state["messages"] = [
            HumanMessage(content="who can apply"),
            AIMessage(content="Children [ASP-001]."),
            HumanMessage(content="and my son?"),
        ]
        assert (await nodes.make_rewrite_query(rewrite)(state))["qa_query"] == "and my son?"


# ── tools ────────────────────────────────────────────────────────────────────


class TestEligibility:
    def test_a_ten_year_old_resident_with_a_guardian_qualifies(self):
        result = tools.check_eligibility(
            date(2016, 3, 14), "citizen", "parent", on=date(2026, 8, 5)
        )
        assert result.eligible
        assert result.age == 10

    def test_the_birthday_not_yet_had_is_handled(self):
        """The off-by-one that every age calculation has once."""
        result = tools.check_eligibility(
            date(2008, 12, 31), "citizen", "parent", on=date(2026, 8, 5)
        )
        assert result.age == 17
        assert result.eligible

    def test_a_child_who_is_too_young_is_told_not_yet(self):
        """They become eligible. The family should be told when, not told no."""
        result = tools.check_eligibility(
            date(2023, 1, 1), "citizen", "parent", on=date(2026, 8, 5)
        )
        assert not result.eligible
        assert "Not yet" in result.reasons[0]

    def test_nineteen_is_over_the_limit(self):
        result = tools.check_eligibility(
            date(2007, 1, 1), "citizen", "parent", on=date(2026, 8, 5)
        )
        assert not result.eligible

    def test_each_criterion_reports_separately(self):
        """A bare yes/no is unusable at a counter."""
        result = tools.check_eligibility(
            date(2016, 1, 1), "visitor", "friend", on=date(2026, 8, 5)
        )
        assert result.criteria == {
            "age_in_range": True,
            "resident": False,
            "has_guardian": False,
        }

    def test_the_result_is_reproducible(self):
        """Reading `date.today()` would make a past check impossible to explain."""
        args = (date(2016, 3, 14), "citizen", "parent")
        assert tools.check_eligibility(*args, on=date(2026, 8, 5)) == tools.check_eligibility(
            *args, on=date(2026, 8, 5)
        )


class TestProjection:
    def test_it_agrees_with_the_formula_registry(self):
        """There is one compound-interest implementation, and the chart uses it."""
        from app.widgets.formulas import registry

        projection = tools.project_savings(0, 5_000, 0.05, 3)
        expected = registry.compound_interest(0, 5_000, 0.05, 3, 12)
        assert projection.final_cents == expected.value

    def test_the_series_has_one_point_per_year(self):
        projection = tools.project_savings(10_000, 1_000, 0.04, 5)
        assert len(projection.series) == 5
        assert projection.series == sorted(projection.series)

    def test_it_emits_a_chart_directive_with_the_computed_points(self):
        projection = tools.project_savings(10_000, 1_000, 0.04, 3)
        assert projection.directive["t"] == "chart"
        assert len(projection.directive["series"][0]["points"]) == 3


class TestChecklistsAndBranches:
    def test_a_known_application_type_has_a_stable_list(self):
        assert [d.slot for d in tools.document_checklist("new_child_account")] == [
            "guardian.id_document",
            "guardian.proof_of_address",
            "child.birth_certificate",
            "child.photo",
        ]

    def test_an_unknown_type_falls_back_rather_than_returning_nothing(self, caplog):
        """A parent given an empty checklist arrives at a branch with nothing."""
        with caplog.at_level("WARNING"):
            assert tools.document_checklist("mystery")
        assert "Unknown application type" in caplog.text

    def test_a_parish_is_matched_loosely(self):
        assert [b.name for b in tools.find_branch("Cayon")] == ["Cayon"]
        assert [b.name for b in tools.find_branch("saint mary")] == ["Cayon"]

    def test_an_unmatched_parish_returns_everything(self):
        assert len(tools.find_branch("Atlantis")) == 5

    def test_an_empty_parish_returns_everything(self):
        assert len(tools.find_branch("")) == 5


class TestHandoffs:
    def test_registration_handoff_sets_the_sticky_agent(self):
        command = tools.handoff_to_registration()
        assert command.goto == "register_agent"
        assert command.update["active_agent"] == "register_agent"

    def test_escalation_redacts_before_the_ticket_exists(self):
        command = tools.escalate_to_human(
            "user_request", "call me on 869-555-0123 about A12345678"
        )
        summary = command.update["escalation"].summary
        assert "869-555-0123" not in summary
        assert "A12345678" not in summary


# ── follow-up chips ──────────────────────────────────────────────────────────


class TestFollowUpChips:
    """Two more questions the corpus can actually answer."""

    def _chunks(self, *questions: str) -> list[KBChunk]:
        return [
            KBChunk(
                kb_id=f"ASP-{index:03d}",
                content="x",
                title=question,
                metadata={"question": question},
            )
            for index, question in enumerate(questions, start=1)
        ]

    def test_chips_come_from_the_retrieved_rows(self):
        chunks = self._chunks(
            "What is the ASPIRE Programme?",
            "What does ASPIRE stand for?",
            "What is the goal of ASPIRE?",
        )
        chips = nodes.follow_up_chips(
            state_for("What is ASPIRE?"), chunks, {"ASP-001"}
        )

        assert chips == ["What does ASPIRE stand for?", "What is the goal of ASPIRE?"]

    def test_the_cited_row_is_never_offered_back(self):
        """A chip repeating the question just answered is a wasted chip."""
        chunks = self._chunks("What is the ASPIRE Programme?", "Who can join?")
        chips = nodes.follow_up_chips(
            state_for("What is ASPIRE?"), chunks, {"ASP-001"}
        )

        assert "What is the ASPIRE Programme?" not in chips

    def test_the_question_just_asked_is_not_offered_back(self):
        chunks = self._chunks("What is ASPIRE?", "Who can join?")
        chips = nodes.follow_up_chips(state_for("what is aspire"), chunks, set())

        assert chips == ["Who can join?"]

    def test_a_question_too_long_to_render_is_dropped_not_truncated(self):
        """Half a question is not a question."""
        chunks = self._chunks("x" * (nodes.CHIP_MAX_CHARS + 1), "Who can join?")
        chips = nodes.follow_up_chips(state_for("q"), chunks, set())

        assert chips == ["Who can join?"]

    def test_never_more_than_the_cap(self):
        """Asserted against the constant, so raising it is one edit and not two."""
        chunks = self._chunks("A?", "B?", "C?", "D?", "E?")
        chips = nodes.follow_up_chips(state_for("q"), chunks, set())
        assert len(chips) == nodes.FOLLOW_UP_CHIPS

    def test_no_retrieval_means_no_chips(self):
        assert nodes.follow_up_chips(state_for("q"), [], set()) == []

    def test_the_snippet_drops_the_column_scaffolding(self):
        """A reader must never be shown `id:` and `subcategory:`.

        `ingest.row_to_document` stores a row as labelled column lines, and the
        sources panel is reader-facing copy, not a database dump.
        """
        row = (
            "Category: Eligibility\n"
            "Question: What is the maximum age to join ASPIRE?\n"
            "Answer: ASPIRE is for young people up to age 18.\n"
            "id: ASP-030\n"
            "subcategory: Age maximum"
        )
        assert nodes.snippet_of(row) == "ASPIRE is for young people up to age 18."

    def test_a_row_with_no_answer_column_keeps_its_text(self):
        """The other schema `ingest` supports must still show something."""
        assert nodes.snippet_of("Just some prose about saving.") == (
            "Just some prose about saving."
        )

    def test_a_fully_cited_answer_still_offers_chips(self):
        """The failure this pool exists for, measured against the live service.

        `qa_rerank_k` is 4, so a good answer is handed four extracts and cites
        all four -- and every candidate is then excluded as already-cited. The
        turn produced NO quick_replies directive at all. The reranker's dropped
        hits are the fallback, and they are the right one: real corpus
        questions, ranked by the same retrieval, that the answer did not use.
        """
        cited = self._chunks("What is ASPIRE?", "Who can join?")
        related = [
            KBChunk(
                kb_id="ASP-090",
                content="x",
                title="What documents are needed?",
                metadata={"question": "What documents are needed?"},
            )
        ]
        chips = nodes.follow_up_chips(
            state_for("tell me about aspire", qa_related=related),
            cited,
            {"ASP-001", "ASP-002"},
        )

        assert chips == ["What documents are needed?"]

    def test_a_chip_restating_a_cited_row_is_not_offered(self):
        """Two rows, one question. Excluding by id alone is not enough.

        Measured: an eligibility answer that cited the maximum-age row offered
        "What is the maximum age cap for ASPIRE participation?" straight back,
        because it is a different row asking the same thing.
        """
        chunks = self._chunks("What is the maximum age to join ASPIRE?")
        related = [
            KBChunk(
                kb_id="ASP-091",
                content="x",
                title="What is the maximum age cap for ASPIRE participation?",
                metadata={
                    "question": "What is the maximum age cap for ASPIRE participation?"
                },
            ),
            KBChunk(
                kb_id="ASP-092",
                content="x",
                title="How do I apply?",
                metadata={"question": "How do I apply?"},
            ),
        ]
        chips = nodes.follow_up_chips(
            state_for("how old can you be", qa_related=related), chunks, {"ASP-001"}
        )

        assert chips == ["How do I apply?"]

    def test_a_question_asked_earlier_in_the_thread_is_not_offered(self):
        """Deduping against the last turn alone is not enough.

        A chip offering something answered six turns ago reads as the assistant
        not having listened, and the reader cannot know it would only repeat.
        """
        state = state_for("What documents are needed?")
        state["messages"] = [
            HumanMessage(content="Who can join ASPIRE?"),
            AIMessage(content="Children aged 5 to 18."),
            HumanMessage(content="What documents are needed?"),
        ]
        chunks = self._chunks("Who can join ASPIRE?", "How do I apply?")
        chips = nodes.follow_up_chips(state, chunks, set())

        assert chips == ["How do I apply?"]

    def test_a_longer_restatement_of_the_question_is_not_offered(self):
        """Different row, same question."""
        chunks = self._chunks(
            "What is the minimum age requirement for ASPIRE enrolment?",
            "What is the maximum age to join ASPIRE?",
        )
        chips = nodes.follow_up_chips(
            state_for("What is the minimum age?"), chunks, set()
        )

        assert chips == ["What is the maximum age to join ASPIRE?"]

    def test_a_one_word_question_does_not_suppress_everything(self):
        """The guard on the guard, and the product's most-asked question."""
        chunks = self._chunks(
            "What does ASPIRE stand for?", "What is the goal of ASPIRE?"
        )
        chips = nodes.follow_up_chips(state_for("What is ASPIRE?"), chunks, set())

        assert len(chips) == 2

    def test_two_chips_are_never_restatements_of_each_other(self):
        chunks = self._chunks(
            "What is compound interest?",
            "Can you explain compound interest?",
            "How do I open an account?",
        )
        chips = nodes.follow_up_chips(state_for("Tell me about saving"), chunks, set())

        assert chips == ["What is compound interest?", "How do I open an account?"]
