"""The defects the Zion run found, pinned.

A seventeen-year-old was walked end to end through the live service in
English and then Spanish -- curiosity, sign-up, compounding, an action plan,
two games, a story he rewrote, and a lesson in three personalities. These are
the three faults from that run that are fixed here, each written as the turn
that produced it.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.escalation.decline import nearest_topic
from app.graph.nodes.classify import _is_an_outright_question
from app.graph.nodes.intents import wants_game, wants_story
from app.graph.state import KBChunk


# ── 1. the form that would not let go ────────────────────────────────────────


def _asking(text: str) -> dict:
    return {"messages": [HumanMessage(content=text)]}


class TestAQuestionWithoutAQuestionMark:
    """Zion, mid-registration: 'can i register on my own or do i need my mother
    to do it' was graded as a bad answer to 'how are you related to the child?'
    -- twice. Teenagers do not type question marks."""

    @pytest.mark.parametrize(
        "text",
        [
            "can i register on my own or do i need my mother to do it",
            "do i need my mother for this",
            "can you tell me what documents i need",
            "should i use my own name here",
            "puedo registrarme yo solo",
            "dois-je demander a ma mere",
        ],
    )
    def test_it_reads_as_a_question(self, text):
        assert _is_an_outright_question(_asking(text)) is True

    @pytest.mark.parametrize(
        "text",
        ["Will", "Will Smith", "Mother", "my mother", "14/03/1985", "Basseterre"],
    )
    def test_a_slot_answer_is_still_an_answer(self, text):
        assert _is_an_outright_question(_asking(text)) is False

    def test_the_wh_words_and_marks_still_work(self):
        assert _is_an_outright_question(_asking("what documents do i need"))
        assert _is_an_outright_question(_asking("mother?"))


# ── 2. the games and stories nobody could ask for ────────────────────────────


class TestTheWaysPeopleActuallyAsk:
    @pytest.mark.parametrize(
        "text",
        ["play a different game", "another one", "juguemos", "jouons",
         "otro juego", "un autre jeu"],
    )
    def test_these_are_game_requests(self, text):
        assert wants_game(text) is True

    @pytest.mark.parametrize(
        "text",
        ["me cuentas un cuento", "¿me puedes contar un cuento?",
         "léeme un cuento", "cuento por favor",
         "peux-tu me raconter une histoire ?", "une histoire s'il te plaît",
         "lis-moi une histoire"],
    )
    def test_these_are_story_requests(self, text):
        assert wants_story(text) is True

    @pytest.mark.parametrize(
        "text",
        ["what games do you have", "que juegos hay", "how does a story work"],
    )
    def test_asking_about_them_is_not_asking_for_them(self, text):
        assert wants_game(text) is False or wants_story(text) is False


# ── 3. the decline that handed back the question ─────────────────────────────


def _chunk(kb_id: str, title: str) -> KBChunk:
    return KBChunk(kb_id=kb_id, content="...", title=title, score=0.5, relevance=0.5)


class TestTheOfferIsNeverTheQuestion:
    """'what documents do i need' was declined with 'You could ask me this one
    instead: "What documents do I need to register?"'"""

    def test_a_restatement_is_skipped_for_the_next_topic(self):
        chunks = [
            _chunk("ASP-1", "What documents do I need to register?"),
            _chunk("ASP-2", "How do I open an ASPIRE account?"),
        ]
        topic = nearest_topic(chunks, "what documents do i need")
        assert topic == "How do I open an ASPIRE account?"

    def test_a_genuinely_different_topic_is_still_offered(self):
        chunks = [_chunk("ASP-1", "What is the minimum opening deposit?")]
        assert nearest_topic(chunks, "who runs ASPIRE") == "What is the minimum opening deposit?"

    def test_nothing_left_to_offer_offers_nothing(self):
        chunks = [_chunk("ASP-1", "What documents do I need to register?")]
        assert nearest_topic(chunks, "what documents do i need") is None

    def test_no_question_to_compare_against_behaves_as_before(self):
        chunks = [_chunk("ASP-1", "What is ASPIRE?")]
        assert nearest_topic(chunks, "") == "What is ASPIRE?"
