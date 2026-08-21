"""Source attribution, end to end: retrieval -> citation -> the wire.

Every test here is one of the acceptance scenarios. What they defend, together,
is a single claim: what the panel shows a reader corresponds to the rows the
answer actually used, and the address behind each one came from the corpus
rather than from a model.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from app import sources  # noqa: E402
from app.agents.qa import nodes  # noqa: E402
from app.agents.qa.graph import build_qa_graph  # noqa: E402
from app.api.stream import CITATION_REFS_MAX, citation_refs  # noqa: E402
from app.graph.main_graph import citation_payload  # noqa: E402
from app.graph.state import Citation, KBChunk, initial_state  # noqa: E402
from app.schemas.directives import CITATION_ID  # noqa: E402

# ── a corpus that says where each row came from ──────────────────────────────

#: `(kb_id, text, metadata)` -- the shape `_corpus` hands the lexical side.
CORPUS: list[tuple[str, str, dict]] = [
    (
        "ASP-001",
        "Question: Who is eligible for ASPIRE?\n"
        "Answer: ASPIRE is open to children aged 5 to 18 who are citizens or residents.",
        {
            "question": "Who is eligible for ASPIRE?",
            "source_url": "https://aspire.gov.kn/#faqs",
            "as_of": "2026-07-30",
        },
    ),
    (
        "ASP-002",
        "Question: What is ASPIRE?\nAnswer: ASPIRE is a national financial education programme.",
        {
            "question": "What is ASPIRE?",
            "source_url": "https://aspire.gov.kn/",
            "as_of": "2026-07-30",
        },
    ),
    (
        "ASP-003",
        "Question: What is the minimum deposit?\nAnswer: The minimum opening deposit is EC$25.",
        {
            "question": "What is the minimum deposit?",
            "source_url": "https://aspire.gov.kn/#faqs",
        },
    ),
    (
        "ASP-004",
        "Question: What does the ECCB do?\nAnswer: The ECCB issues the EC dollar.",
        {"question": "What does the ECCB do?", "source_url": "https://www.eccb-centralbank.org/"},
    ),
    (
        "ASP-005",
        "Question: What is compound interest?\n"
        "Answer: Interest that earns interest, taught in the ASPIRE workbook.",
        {
            "question": "What is compound interest?",
            "source_url": "internal:aspire-financial-education",
        },
    ),
    (
        "ASP-006",
        "Question: When does the window close?\nAnswer: Applications close on 31 March.",
        # Deliberately sourceless: a row the corpus could not attribute.
        {"question": "When does the window close?"},
    ),
    (
        "ASP-007",
        "Question: Where is the branch?\nAnswer: The Basseterre branch is on Central Street.",
        # Deliberately broken: what a hand-edited row looks like.
        {"question": "Where is the branch?", "source_url": "knowledge_base.csv"},
    ),
]

_BY_ID = {row[0]: row for row in CORPUS}


def chunks_for(*ids: str, relevance: float = 0.9) -> list[KBChunk]:
    """Chunks as the dense retriever produces them, provenance and all."""
    out = []
    for kb_id in ids:
        _, content, metadata = _BY_ID[kb_id]
        out.append(
            KBChunk(
                kb_id=kb_id,
                title=str(metadata.get("question") or ""),
                content=content,
                score=relevance,
                relevance=relevance,
                source="dense",
                source_url=str(metadata.get("source_url") or ""),
                metadata=dict(metadata),
            )
        )
    return out


def state_for(question: str, **overrides):
    state = initial_state(
        session_id="s-cite",
        user_id="u-cite",
        device_id="d",
        persona=overrides.pop("persona", "aurora"),
        age_band=overrides.pop("age_band", "adult"),
        account_status="guardian",
    )
    state["messages"] = [HumanMessage(content=question)]
    state["active_agent"] = "qa_agent"
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


@dataclass
class Reader:
    """The fields `citation_refs` reads off a session's claims."""

    persona: str = "aurora"
    age_band: str = "adult"


def refs_for(state_update: dict, reader: Reader | None = None):
    """A finished turn's citations, as the client would receive them."""
    payload = [citation_payload(c) for c in state_update.get("citations") or []]
    return citation_refs(payload, claims=reader or Reader())


# ── Test 1: a question the knowledge base answers ────────────────────────────


class TestBasicAttribution:
    @pytest.mark.asyncio
    async def test_a_grounded_answer_carries_a_real_clickable_source(self):
        graph = build_qa_graph(
            search=dense_returning("ASP-001"),
            corpus=corpus,
            generate_invoke=generating(
                "ASPIRE is open to children aged 5 to 18 [ASP-001]."
            ),
        )
        result = await graph.ainvoke(state_for("who is eligible for aspire"))

        refs = refs_for(result)
        assert len(refs) == 1
        assert refs[0].kb_id == "ASP-001"
        assert refs[0].source_url == "https://aspire.gov.kn/#faqs"
        assert refs[0].domain == "aspire.gov.kn"
        assert refs[0].site == "ASPIRE"
        # §26: what reaches an `href` must survive validation.
        assert sources.safe_url(refs[0].source_url) == refs[0].source_url

    @pytest.mark.asyncio
    async def test_the_source_is_the_row_the_answer_cited_and_not_the_others(self):
        """§7 and §18: retrieval finds ten, the answer used one, one is shown."""
        state = state_for("what is the minimum deposit")
        state["retrieved"] = chunks_for("ASP-003", "ASP-001", "ASP-002", "ASP-004")
        state["messages"].append(
            AIMessage(content="The minimum opening deposit is EC$25 [ASP-003].")
        )

        command = await nodes.make_ground_check()(state)
        assert [c.kb_id for c in command.update["citations"]] == ["ASP-003"]


# ── Test 2: the specific page, not the site ──────────────────────────────────


class TestPagePrecision:
    @pytest.mark.asyncio
    async def test_a_row_cites_its_own_page_rather_than_the_homepage(self):
        """§5: prefer `/#faqs` over `/` when the answer came from the FAQ."""
        state = state_for("who is eligible")
        state["retrieved"] = chunks_for("ASP-001")
        state["messages"].append(AIMessage(content="Children aged 5 to 18 [ASP-001]."))

        citation = (await nodes.make_ground_check()(state)).update["citations"][0]
        assert citation.source_url == "https://aspire.gov.kn/#faqs"
        assert citation.page == "Frequently asked questions"

    @pytest.mark.asyncio
    async def test_two_rows_on_one_site_keep_their_different_pages(self):
        state = state_for("what is aspire and who is eligible")
        state["retrieved"] = chunks_for("ASP-002", "ASP-001")
        state["messages"].append(
            AIMessage(content="A national programme [ASP-002] for ages 5 to 18 [ASP-001].")
        )

        refs = refs_for((await nodes.make_ground_check()(state)).update)
        assert {ref.source_url for ref in refs} == {
            "https://aspire.gov.kn/",
            "https://aspire.gov.kn/#faqs",
        }


# ── Test 3: several sources at once ──────────────────────────────────────────


class TestMultipleSources:
    @pytest.mark.asyncio
    async def test_an_answer_built_from_three_rows_shows_three_sources(self):
        state = state_for("who is eligible, what is aspire, and what does the eccb do")
        state["retrieved"] = chunks_for("ASP-001", "ASP-002", "ASP-004")
        state["messages"].append(
            AIMessage(
                content="Ages 5 to 18 [ASP-001]. A national programme [ASP-002]. "
                "The ECCB issues the EC dollar [ASP-004]."
            )
        )

        refs = refs_for((await nodes.make_ground_check()(state)).update)
        assert len(refs) == 3
        assert len({sources.canonical(ref.source_url) for ref in refs}) == 3
        assert all(ref.source_url for ref in refs)


# ── Test 4 and 5: answers that are not retrieval ─────────────────────────────


class TestArithmeticIsNotAttributed:
    @pytest.mark.asyncio
    async def test_a_sum_the_corpus_never_mentioned_shows_no_source(self):
        """§14: `25 + 15` is not a knowledge-base question and cites nothing."""
        graph = build_qa_graph(
            search=dense_returning("ASP-002"),
            corpus=corpus,
            generate_invoke=generating("40."),
        )
        result = await graph.ainvoke(state_for("what is 25 + 15?"))

        assert refs_for(result) == []

    @pytest.mark.asyncio
    async def test_a_conversational_turn_shows_no_source(self):
        state = state_for("thanks!")
        state["retrieved"] = chunks_for("ASP-001")

        command = await nodes.make_ground_check()(state)
        assert command.update["citations"] == []

    @pytest.mark.asyncio
    async def test_a_hybrid_answer_attributes_the_fact_and_not_the_sum(self):
        """§15: the source belongs to the retrieved figure, not to the arithmetic."""
        state = state_for("if the minimum deposit is EC$25, what do 4 of them cost?")
        state["retrieved"] = chunks_for("ASP-003")
        state["messages"].append(
            AIMessage(
                content="The minimum opening deposit is EC$25 [ASP-003], so four "
                "of them is EC$100."
            )
        )

        refs = refs_for((await nodes.make_ground_check()(state)).update)
        assert [ref.kb_id for ref in refs] == ["ASP-003"]
        # The row it points at contains the EC$25; nothing claims to source the EC$100.
        assert "EC$25" in refs[0].snippet
        assert "EC$100" not in refs[0].snippet


class TestTheCitationMarkerIsNotAFigure:
    """`[ASP-011]` contains the digits `011`, and the role card demands it.

    The gate was reading an answer's own citation as an invented number. It
    never showed because `known` was built from the raw row text, whose
    `id: ASP-011` line licensed the marker by accident — and scrubbing that
    line out of the prompt took the accident with it.
    """

    def test_a_marker_does_not_make_a_correct_answer_ungrounded(self):
        chunks = [
            KBChunk(
                kb_id="ASP-742",
                content="Answer: Applications are reviewed by the programme office.",
                relevance=0.9,
            )
        ]
        answer = "Applications are reviewed by the programme office [ASP-742]."
        assert nodes.unattributed_figures(answer, chunks, "", "who reviews them?") == []

    @pytest.mark.parametrize("marker", ["ASP-011", "FIN-4212", "RES-99"])
    def test_no_reference_id_reads_as_a_claim(self, marker: str):
        chunks = [KBChunk(kb_id=marker, content="Answer: The office is on Central Street.")]
        assert (
            nodes.unattributed_figures(
                f"The office is on Central Street [{marker}].", chunks, "", "where is it?"
            )
            == []
        )

    @pytest.mark.parametrize("kb_id", ["ASP-001", "ASP-00A", "ASP-00B", "FIN-4212", "RES-007"])
    def test_an_id_that_is_not_all_digits_still_cites(self, kb_id: str):
        """`ASP-00A` is an id somebody wrote, and three readers disagreed on it.

        Grounding, the figure gate and the interceptor each had their own copy
        of the marker pattern, and two of the three demanded digits after the
        hyphen. The two rows that define what completing the programme means
        are `ASP-00A` and `ASP-00B`: every answer drawn from them was declined
        as uncited, and the marker was left in the prose for the reader to see.
        """
        from app.graph.stream_interceptor import strip_citation_markers

        chunks = [KBChunk(kb_id=kb_id, content="Answer: Stay five years or until 18.")]
        answer = f"Stay five years or until 18 [{kb_id}]."

        assert nodes.unattributed_figures(answer, chunks, "", "how long?") == []
        cited = set(re.findall(rf"\[({CITATION_ID})\]", answer))
        assert cited == {kb_id}
        assert kb_id not in strip_citation_markers(answer)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kb_id", ["ASP-00A", "ASP-00B"])
    async def test_the_rows_defining_completion_are_actually_served(self, kb_id: str):
        state = state_for("what does completing the programme mean")
        state["retrieved"] = [
            KBChunk(
                kb_id=kb_id,
                content="Answer: Stay a minimum of 5 years or until 18, whichever is later.",
                relevance=0.9,
                source_url="https://aspire.gov.kn/",
                metadata={"question": "What does completing mean?"},
            )
        ]
        state["messages"].append(
            AIMessage(content=f"A minimum of 5 years or until 18, whichever is later [{kb_id}].")
        )

        command = await nodes.make_ground_check()(state)
        assert [c.kb_id for c in command.update["citations"]] == [kb_id]

    def test_every_corpus_row_answering_itself_is_served(self):
        """The measurement that caught it: 684 of 706 correct answers declined."""
        from pathlib import Path

        from app.ingest import load_documents

        corpus = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.csv"
        declined = []
        for document in load_documents(corpus):
            kb_id = str(document.metadata.get("id") or "")
            chunk = KBChunk(kb_id=kb_id, content=document.page_content, relevance=0.9)
            answer = f"{document.metadata.get('answer', '')} [{kb_id}]"
            missing = nodes.unattributed_figures(
                answer, [chunk], "", str(document.metadata.get("question", ""))
            )
            if missing:
                declined.append((kb_id, missing[:3]))

        assert not declined, f"{len(declined)} correct answers would be refused: {declined[:5]}"


class TestTheFigureGateAndArithmetic:
    """What a worked example may state without being read as an invention.

    The gate exists to catch a figure the model made up. It could not tell that
    from a figure the model calculated, so it declined hybrid answers whole.
    """

    def test_a_figure_calculated_from_an_extract_is_attributed_to_the_sum(self):
        chunks = chunks_for("ASP-003")  # "The minimum opening deposit is EC$25."
        assert (
            nodes.unattributed_figures(
                "EC$25 four times over is EC$100.", chunks, "", "what do 4 deposits cost?"
            )
            == []
        )

    def test_a_figure_calculated_from_the_readers_own_numbers_is_fine(self):
        """§14: EC$10 a week for 5 weeks is EC$50, and no corpus row says so."""
        chunks = chunks_for("ASP-002")
        assert (
            nodes.unattributed_figures(
                "That would be EC$50 after five weeks.",
                chunks,
                "",
                "if I save EC$10 every week for 5 weeks, how much will I have?",
            )
            == []
        )

    def test_a_percentage_of_a_given_amount_is_fine(self):
        chunks = chunks_for("ASP-003")
        assert (
            nodes.unattributed_figures(
                "20% of EC$25 is EC$5.", chunks, "", "what is 20% of the deposit?"
            )
            == []
        )

    def test_the_working_may_restate_the_figures_it_worked_from(self):
        """EC$500 is the reader's own; it is here as the sum, not as a claim."""
        chunks = chunks_for("ASP-002")
        assert (
            nodes.unattributed_figures(
                "20% of EC$500 is EC$100.",
                chunks,
                "",
                "what is 20% of EC$500?",
            )
            == []
        )

    def test_a_figure_the_reader_named_cannot_be_asserted_straight_back(self):
        """The injection this gate has to stop.

        Nothing was worked out, so the figure in the answer is the figure in
        the question wearing a fact's clothes.
        """
        chunks = chunks_for("ASP-002")
        assert nodes.unattributed_figures(
            "Yes, ASPIRE pays EC$9,999 to every participant.",
            chunks,
            "",
            "does ASPIRE pay EC$9,999 to every participant?",
        ) == ["EC$9,999"]

    def test_one_real_sum_does_not_license_every_other_figure_the_reader_named(self):
        """The licence is per figure, not per turn.

        EC$10 was worked out, so restating the 20 and the EC$50 behind it is
        the working. The EC$9,999 in the same breath took part in nothing.
        """
        chunks = chunks_for("ASP-002")
        missing = nodes.unattributed_figures(
            "20% of EC$50 is EC$10. And yes, ASPIRE pays EC$9,999.",
            chunks,
            "",
            "what is 20% of EC$50, and does ASPIRE pay EC$9,999?",
        )
        assert missing == ["EC$9,999"]

    def test_a_readers_figure_cannot_be_both_operands_of_its_own_licence(self):
        """`given` contains `asked`, so `x + x` and `x * x` were derivable."""
        chunks = chunks_for("ASP-002")
        assert nodes.unattributed_figures(
            "ASPIRE pays EC$19,998 in total.", chunks, "", "does it pay EC$9,999 each?"
        ) == ["EC$19,998"]

    def test_an_identity_operation_does_not_count_as_working_it_out(self):
        """`9999 * 1` is 9999, and a corpus row with a 1 in it is not a calculator."""
        chunks = chunks_for("ASP-001")  # contains "5" and "18"
        assert nodes.unattributed_figures(
            "ASPIRE pays EC$9,999.", chunks, "", "does it pay EC$9,999?"
        ) == ["EC$9,999"]

    def test_a_figure_that_follows_from_nothing_is_still_caught(self):
        """The gate is narrowed, not opened. This is what it is for."""
        chunks = chunks_for("ASP-003")
        assert nodes.unattributed_figures(
            "The programme pays EC$7,431 a year.", chunks, "", "how much does it pay?"
        ) == ["EC$7,431"]

    def test_a_factual_question_gets_no_arithmetic_exemption_at_all(self):
        """The reader asked for a fact, so nothing here is a calculation.

        EC$50 IS two EC$25 deposits, and on a question that named no figure
        that is a coincidence rather than a working. The exemption applies only
        where the reader supplied a number to compute with.
        """
        chunks = chunks_for("ASP-003")  # "The minimum opening deposit is EC$25."
        assert nodes.unattributed_figures(
            "The programme pays EC$50.", chunks, "", "how much does the programme pay?"
        ) == ["EC$50"]

    def test_the_same_figure_is_allowed_once_the_reader_asks_for_the_sum(self):
        chunks = chunks_for("ASP-003")
        assert (
            nodes.unattributed_figures(
                "Two of them is EC$50.", chunks, "", "what do 2 deposits cost?"
            )
            == []
        )

    def test_the_gate_still_bites_against_a_figure_dense_retrieval(self):
        """The guards above use one-figure chunks; a real retrieval is not that.

        Four rows out of the live corpus average several figures each, which is
        the case where an over-broad exemption would quietly stop catching
        anything. Every one of these is a fabrication and every one must be
        named.
        """
        dense = [
            KBChunk(
                kb_id="ASP-100",
                content=(
                    "Answer: The seed deposit is EC$500 and the minimum opening "
                    "deposit is EC$25. Applications close on 31 March. Children "
                    "aged 5 to 18 qualify, and interest is credited twice a year "
                    "at 2.5%. Call 869 467 1000."
                ),
            ),
            KBChunk(
                kb_id="ASP-101",
                content="Answer: The ECCB was established in 1983 and serves 8 member states.",
            ),
        ]
        for invented in ("EC$1,750", "EC$3,200", "7.5%", "EC$640"):
            assert nodes.unattributed_figures(
                f"Participants receive {invented}.", dense, "", "what do participants receive?"
            ) == [invented], f"{invented} slipped through"

    def test_a_figure_derived_only_from_two_extracts_is_still_caught(self):
        """The model adding up two corpus figures unprompted is not a worked example."""
        chunks = chunks_for("ASP-003", "ASP-001")  # EC$25, and ages 5 to 18
        assert nodes.unattributed_figures(
            "That comes to EC$43.", chunks, "", "what does it come to?"
        ) == ["EC$43"]

    def test_a_rate_the_corpus_never_stated_is_still_caught(self):
        chunks = chunks_for("ASP-002")
        assert nodes.unattributed_figures("The rate is 4.5%.", chunks) == ["4.5%"]

    @pytest.mark.asyncio
    async def test_a_hybrid_turn_is_served_rather_than_declined(self):
        state = state_for("if the minimum deposit is EC$25, what do 4 of them cost?")
        state["retrieved"] = chunks_for("ASP-003")
        state["messages"].append(
            AIMessage(
                content="The minimum opening deposit is EC$25 [ASP-003], so four "
                "of them is EC$100."
            )
        )

        command = await nodes.make_ground_check()(state)
        assert [c.kb_id for c in command.update["citations"]] == ["ASP-003"]

    @pytest.mark.asyncio
    async def test_a_hybrid_turn_still_has_to_cite_its_factual_half(self):
        """Arithmetic is not a licence to skip grounding."""
        state = state_for("if the minimum deposit is EC$25, what do 4 of them cost?")
        state["retrieved"] = chunks_for("ASP-003")
        state["messages"].append(AIMessage(content="Four of them is EC$100."))

        command = await nodes.make_ground_check()(state)
        assert command.update.get("citations", []) == []


# ── Test 6: a row with nothing to link to ────────────────────────────────────


class TestMissingSourceMetadata:
    @pytest.mark.asyncio
    async def test_a_row_with_no_url_cites_without_one_and_invents_nothing(self):
        """§6 and §19: no fabricated URL, and the turn still works."""
        state = state_for("when does the window close")
        state["retrieved"] = chunks_for("ASP-006")
        state["messages"].append(AIMessage(content="Applications close on 31 March [ASP-006]."))

        refs = refs_for((await nodes.make_ground_check()(state)).update)
        assert len(refs) == 1
        assert refs[0].source_url == ""
        assert refs[0].domain == ""
        # The evidence still shows: the row's own question and its own words.
        assert refs[0].question == "When does the window close?"
        assert refs[0].snippet

    @pytest.mark.asyncio
    async def test_a_row_with_no_url_is_logged_for_developers(self, caplog):
        state = state_for("when does the window close")
        state["retrieved"] = chunks_for("ASP-006")
        state["messages"].append(AIMessage(content="Applications close on 31 March [ASP-006]."))

        with caplog.at_level("INFO"):
            await nodes.make_ground_check()(state)
        assert any("no usable source" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_material_with_no_public_page_is_named_but_not_linked(self):
        state = state_for("what is compound interest")
        state["retrieved"] = chunks_for("ASP-005")
        state["messages"].append(
            AIMessage(content="Interest that earns interest [ASP-005].")
        )

        refs = refs_for((await nodes.make_ground_check()(state)).update)
        assert refs[0].source_url == ""
        assert refs[0].page == "ASPIRE financial education material"


# ── Test 7: the same page, several times ─────────────────────────────────────


class TestDuplicateSources:
    @pytest.mark.asyncio
    async def test_rows_off_one_page_all_carry_that_page(self):
        """Each row keeps its true source; the panel is what collapses them."""
        state = state_for("eligibility and the deposit")
        state["retrieved"] = chunks_for("ASP-001", "ASP-003")
        state["messages"].append(
            AIMessage(content="Ages 5 to 18 [ASP-001] and EC$25 [ASP-003].")
        )

        refs = refs_for((await nodes.make_ground_check()(state)).update)
        assert len(refs) == 2
        assert {sources.canonical(ref.source_url) for ref in refs} == {
            "https://aspire.gov.kn/#faqs"
        }

    def test_the_canonical_key_is_what_collapses_them(self):
        """§9 and §10: one page, however it is spelled, is one source."""
        spellings = [
            "https://aspire.gov.kn/program",
            "https://aspire.gov.kn/program/",
            "https://www.aspire.gov.kn/program",
            "https://aspire.gov.kn/program?utm_source=news",
            "http://aspire.gov.kn/program",
        ]
        assert len({sources.canonical(url) for url in spellings}) == 1


# ── Test 8: a URL that will not validate ─────────────────────────────────────


class TestBrokenUrls:
    @pytest.mark.asyncio
    async def test_a_malformed_stored_url_never_becomes_a_link(self):
        state = state_for("where is the branch")
        state["retrieved"] = chunks_for("ASP-007")
        state["messages"].append(
            AIMessage(content="The Basseterre branch is on Central Street [ASP-007].")
        )

        refs = refs_for((await nodes.make_ground_check()(state)).update)
        assert len(refs) == 1
        assert refs[0].source_url == ""
        assert refs[0].kb_id == "ASP-007"

    def test_a_hostile_url_stored_by_an_older_build_is_dropped_at_the_wire(self):
        """§27: `citation_refs` re-validates, because history is not re-derived."""
        stored = [
            {"kb_id": "ASP-009", "source_url": "javascript:alert(1)", "site": "ASPIRE"},
            {"kb_id": "ASP-010", "source_url": "http://localhost:9000/admin", "site": "ASPIRE"},
            {"kb_id": "ASP-011", "source_url": "https://aspire.gov.kn/", "site": "ASPIRE"},
        ]
        refs = citation_refs(stored, claims=Reader())
        assert [ref.source_url for ref in refs] == ["", "", "https://aspire.gov.kn/"]
        # Dropping the link does not drop the attribution.
        assert all(ref.site == "ASPIRE" for ref in refs)

    def test_tracking_parameters_are_stripped_before_the_href(self):
        stored = [{"kb_id": "ASP-001", "source_url": "https://aspire.gov.kn/p?utm_source=x&id=2"}]
        assert citation_refs(stored, claims=Reader())[0].source_url == "https://aspire.gov.kn/p?id=2"


# ── Test 9: the same question in three languages ─────────────────────────────


class TestMultilingual:
    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    @pytest.mark.asyncio
    async def test_the_source_is_the_same_verified_page_in_every_language(
        self, locale: str
    ):
        """§32: the answer is translated; the page it came from is not."""
        answers = {
            "en": "ASPIRE is a national financial education programme [ASP-002].",
            "es": "ASPIRE es un programa nacional de educación financiera [ASP-002].",
            "fr": "ASPIRE est un programme national d'éducation financière [ASP-002].",
        }
        state = state_for("what is aspire", locale=locale)
        state["retrieved"] = chunks_for("ASP-002")
        state["messages"].append(AIMessage(content=answers[locale]))

        refs = refs_for((await nodes.make_ground_check()(state)).update)
        assert [ref.source_url for ref in refs] == ["https://aspire.gov.kn/"]


# ── Test 10: one conversation, several questions ─────────────────────────────


class TestAcrossTurns:
    def test_the_hydrate_node_clears_last_turn_s_citations(self):
        """§31: a new answer must never inherit the previous answer's sources."""
        from app.graph.state import RESET, merge_citations

        previous = [Citation(kb_id="ASP-001", url="https://aspire.gov.kn/#faqs")]
        assert merge_citations(previous, RESET) == []

    def test_citations_from_two_nodes_in_one_turn_merge_without_duplicating(self):
        from app.graph.state import merge_citations

        first = [Citation(kb_id="ASP-001", url="https://aspire.gov.kn/#faqs")]
        again = [
            Citation(kb_id="ASP-001", url="https://aspire.gov.kn/#faqs"),
            Citation(kb_id="ASP-002", url="https://aspire.gov.kn/"),
        ]
        assert [c.kb_id for c in merge_citations(first, again)] == ["ASP-001", "ASP-002"]

    @pytest.mark.asyncio
    async def test_two_questions_in_a_row_get_their_own_sources(self):
        graph = build_qa_graph(
            search=dense_returning("ASP-002"), corpus=corpus,
            generate_invoke=generating("A national programme [ASP-002]."),
        )
        first = await graph.ainvoke(state_for("what is aspire"))
        assert [c.source_url for c in first["citations"]] == ["https://aspire.gov.kn/"]

        graph = build_qa_graph(
            search=dense_returning("ASP-004"), corpus=corpus,
            generate_invoke=generating("The ECCB issues the EC dollar [ASP-004]."),
        )
        second = await graph.ainvoke(state_for("what does the eccb do"))
        assert [c.source_url for c in second["citations"]] == ["https://www.eccb-centralbank.org/"]


# ── the pipeline's own joins ─────────────────────────────────────────────────


class TestMetadataSurvivesEveryHop:
    @pytest.mark.asyncio
    async def test_a_lexical_only_hit_keeps_its_source(self):
        """The hole this work opened with: BM25 built chunks from text alone."""
        node = nodes.make_hybrid_retrieve(dense_returning("ASP-002"), corpus)
        result = await node(state_for("minimum opening deposit EC$25"))

        found = {chunk.kb_id: chunk for chunk in result["retrieved"]}
        assert "ASP-003" in found, "BM25 should have found the exact-term row"
        assert found["ASP-003"].source_url == "https://aspire.gov.kn/#faqs"
        assert found["ASP-003"].title == "What is the minimum deposit?"

    @pytest.mark.asyncio
    async def test_a_corpus_that_carries_no_metadata_still_retrieves(self):
        """The eval harness and the older tests hand in plain `(id, text)` pairs."""

        async def short_form(audience: str = "all"):
            return [(kb_id, content) for kb_id, content, _ in CORPUS]

        node = nodes.make_hybrid_retrieve(dense_returning("ASP-002"), short_form)
        result = await node(state_for("minimum opening deposit EC$25"))
        assert any(chunk.kb_id == "ASP-003" for chunk in result["retrieved"])

    def test_reranking_carries_the_source_through(self):
        chunk = chunks_for("ASP-001")[0]
        moved = chunk.model_copy(update={"score": 0.2})
        assert moved.source_url == "https://aspire.gov.kn/#faqs"
        assert moved.metadata["as_of"] == "2026-07-30"

    def test_the_wire_payload_carries_every_field_the_panel_renders(self):
        """`_publish_turn` used to enumerate four fields by hand and drop the rest."""
        citation = Citation(
            kb_id="ASP-001",
            title="Who is eligible for ASPIRE?",
            question="Who is eligible for ASPIRE?",
            snippet="Ages 5 to 18.",
            url="https://aspire.gov.kn/#faqs",
            site="ASPIRE",
            page="Frequently asked questions",
            domain="aspire.gov.kn",
            updated="2026-07-30",
        )
        payload = citation_payload(citation)
        for field in ("kb_id", "title", "question", "snippet", "source_url", "site", "page", "domain"):
            assert payload[field] == getattr(citation, field)

    def test_a_citation_resumed_from_a_checkpoint_is_read_back_whole(self):
        stored = {
            "kb_id": "ASP-001",
            "source_url": "https://aspire.gov.kn/#faqs",
            "site": "ASPIRE",
            "page": "Frequently asked questions",
        }
        assert citation_payload(stored)["source_url"] == "https://aspire.gov.kn/#faqs"

    def test_a_turn_stored_before_the_url_existed_still_reads_back(self):
        """A citation written by an older build has no url key at all."""
        payload = citation_payload({"kb_id": "ASP-001", "title": "t", "snippet": "s"})
        assert payload["kb_id"] == "ASP-001"
        assert payload["source_url"] == ""


# ── who is shown a link ──────────────────────────────────────────────────────


class TestTheLinkGate:
    STORED = [{"kb_id": "ASP-001", "source_url": "https://aspire.gov.kn/", "site": "ASPIRE",
               "page": "Official website", "domain": "aspire.gov.kn"}]

    def test_an_adult_reader_gets_the_link(self):
        assert citation_refs(self.STORED, claims=Reader("nova", "adult"))[0].source_url

    @pytest.mark.parametrize(
        "persona,band", [("stella", "5-8"), ("stella", "9-12"), ("orion", "13-15")]
    )
    def test_a_reader_who_is_shown_no_links_is_shown_no_link_here_either(
        self, persona: str, band: str
    ):
        """The panel is not a way around `safety_out.strips_links`."""
        refs = citation_refs(self.STORED, claims=Reader(persona, band))
        assert refs[0].source_url == ""

    @pytest.mark.parametrize(
        "persona,band", [("stella", "5-8"), ("orion", "13-15")]
    )
    def test_withholding_the_link_never_withholds_the_attribution(
        self, persona: str, band: str
    ):
        """§33: the source is still named. Only the address is gone."""
        refs = citation_refs(self.STORED, claims=Reader(persona, band))
        assert refs[0].site == "ASPIRE"
        assert refs[0].page == "Official website"

    @pytest.mark.parametrize(
        "persona,band", [("stella", "5-8"), ("orion", "13-15")]
    )
    def test_the_domain_goes_with_the_link_and_not_beside_it(
        self, persona: str, band: str
    ):
        """`aspire.gov.kn` is a URL written shorter, and this reader gets none."""
        assert citation_refs(self.STORED, claims=Reader(persona, band))[0].domain == ""

    def test_a_reader_who_gets_links_gets_the_domain_too(self):
        refs = citation_refs(self.STORED, claims=Reader("nova", "adult"))
        assert refs[0].domain == "aspire.gov.kn"

    def test_a_host_used_as_its_own_name_is_withheld_along_with_the_domain(self):
        """An unregistered source is named by its hostname, which is still a URL.

        Blanking `domain` alone handed the same string straight back in `site`.
        """
        unregistered = [
            {
                "kb_id": "ASP-500",
                "source_url": "https://consumerfinance.gov/saving/",
                "site": "consumerfinance.gov",
                "page": "Saving",
                "domain": "consumerfinance.gov",
            }
        ]
        ref = citation_refs(unregistered, claims=Reader("stella", "5-8"))[0]
        assert ref.source_url == ""
        assert ref.domain == ""
        assert ref.site == ""
        # Still attributed: the page title, the row id and the row's own words.
        assert ref.page == "Saving"
        assert ref.kb_id == "ASP-500"

    def test_a_real_site_name_is_kept_even_when_the_link_is_withheld(self):
        """Only a name that IS the hostname goes. "ASPIRE" is not one."""
        ref = citation_refs(self.STORED, claims=Reader("stella", "5-8"))[0]
        assert ref.site == "ASPIRE"

    def test_a_reader_who_gets_links_keeps_a_hostname_name(self):
        unregistered = [
            {
                "kb_id": "ASP-500",
                "source_url": "https://consumerfinance.gov/saving/",
                "site": "consumerfinance.gov",
                "domain": "consumerfinance.gov",
            }
        ]
        ref = citation_refs(unregistered, claims=Reader("nova", "adult"))[0]
        assert ref.site == "consumerfinance.gov"
        assert ref.source_url == "https://consumerfinance.gov/saving/"

    def test_an_older_orion_gets_the_link(self):
        assert citation_refs(self.STORED, claims=Reader("orion", "16-18"))[0].source_url

    def test_an_unidentified_reader_is_treated_as_the_youngest_one(self):
        """The gate fails closed: not knowing who this is withholds the link."""
        assert citation_refs(self.STORED, claims=None)[0].source_url == ""
        assert citation_refs(self.STORED, claims=Reader("", ""))[0].source_url == ""

    def test_a_claims_object_missing_the_fields_altogether_withholds(self):
        """A call site that forgets to thread claims must not open the gate."""

        class Nothing:
            pass

        assert citation_refs(self.STORED, claims=Nothing())[0].source_url == ""


# ── caps and shape ───────────────────────────────────────────────────────────


class TestTheWireContract:
    def test_a_turn_may_not_send_more_rows_than_the_directive_allows(self):
        stored = [
            {"kb_id": f"ASP-{n:03d}", "source_url": f"https://site{n}.example/p"} for n in range(30)
        ]
        assert len(citation_refs(stored, claims=Reader())) == CITATION_REFS_MAX

    def test_an_internal_grounding_field_never_reaches_the_client(self):
        """`supports` is how grounding talks to itself, not provenance."""
        refs = citation_refs(
            [{"kb_id": "ASP-001", "supports": "the clause it backs"}], claims=Reader()
        )
        assert not hasattr(refs[0], "supports")

    def test_a_ref_is_json_serialisable_with_every_field_present(self):
        payload = citation_refs(
            [{"kb_id": "ASP-001", "source_url": "https://aspire.gov.kn/"}], claims=Reader()
        )[0].model_dump()
        assert set(payload) == {
            "kb_id", "title", "question", "snippet", "source_url", "site", "page", "domain", "updated",
        }

    def test_junk_in_the_stored_list_is_skipped_rather_than_raising(self):
        assert citation_refs(["not a dict", None, {"kb_id": "ASP-001"}], claims=Reader()) != []

    def test_no_citations_produces_no_refs(self):
        """§30: the absence of sources must be an ordinary, quiet state."""
        assert citation_refs([], claims=Reader()) == []


class TestTheShapeHistoryHandsBack:
    """What `/api/conversations/{id}` returns has to be what the client parses.

    These two shapes drifted once already: the server persisted a flat citation
    dict with a `snippet`, the client's `normaliseSource` looked for `content`,
    and every reopened conversation lost the evidence under its sources while
    the live panel kept it. Nothing failed; the text was just gone.
    """

    STORED = {
        "kb_id": "ASP-001",
        "title": "Who is eligible?",
        "question": "Who is eligible for ASPIRE?",
        "snippet": "Children aged 5 to 18.",
        "source_url": "https://aspire.gov.kn/#faqs",
        "site": "ASPIRE",
        "page": "Frequently asked questions",
        "domain": "aspire.gov.kn",
        "updated": "2026-07-30",
        # An internal field an older turn wrote, which must not go out.
        "supports": "the clause about ages",
    }

    @staticmethod
    def replayed(stored: dict, reader: Reader | None = None) -> dict:
        """One stored citation as `/api/conversations/{id}` sends it."""
        from app.conversations import _replayed_sources

        return _replayed_sources([stored], reader or Reader())[0]

    def test_the_keys_are_exactly_the_ones_the_client_reads(self):
        """`normaliseSource` splits these into `content`, `metadata` and `origin`."""
        assert set(self.replayed(self.STORED)) == {
            "kb_id", "title", "question", "snippet", "source_url", "site", "page", "domain", "updated",
        }

    def test_the_evidence_survives_the_round_trip(self):
        """The bug this guards: `snippet` reaching the client and rendering as nothing."""
        assert self.replayed(self.STORED)["snippet"] == "Children aged 5 to 18."

    def test_the_source_survives_the_round_trip(self):
        replayed = self.replayed(self.STORED)
        assert replayed["source_url"] == "https://aspire.gov.kn/#faqs"
        assert replayed["site"] == "ASPIRE"
        assert replayed["page"] == "Frequently asked questions"

    def test_an_internal_grounding_field_does_not_come_back(self):
        assert "supports" not in self.replayed(self.STORED)

    def test_history_obeys_the_same_link_gate_a_live_turn_does(self):
        """Reopening a conversation must not hand a child what the live turn withheld."""
        replayed = self.replayed(self.STORED, Reader("stella", "5-8"))
        assert replayed["source_url"] == ""
        assert replayed["domain"] == ""
        assert replayed["site"] == "ASPIRE"

    def test_a_stored_turn_from_before_provenance_existed_still_replays(self):
        old = {"kb_id": "ASP-001", "question": "Who is eligible?", "snippet": "Ages 5 to 18."}
        replayed = self.replayed(old)
        assert replayed["snippet"] == "Ages 5 to 18."
        assert replayed["source_url"] == ""
