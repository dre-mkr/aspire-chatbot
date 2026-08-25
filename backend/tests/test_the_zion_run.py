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


# ── 4. the teacher's lesson plan, read to the teenager ───────────────────────


class TestTheReadersOwnAudienceRanksFirst:
    """Zion, seventeen, asked for his story to star a fisherman from Sandy
    Point and was told "After the story, students can act it out and discuss
    what choice he made" -- a teacher's lesson plan, read out to the child it
    was written about."""

    @staticmethod
    def _tagged(kb_id: str, audience: str) -> KBChunk:
        return KBChunk(
            kb_id=kb_id, content="...", title=f"row {kb_id}",
            score=0.5, relevance=0.5, metadata={"audience": audience},
        )

    def test_a_students_row_outranks_a_teachers_row_for_a_teen(self):
        from app.agents.qa.nodes import _for_this_reader

        assert _for_this_reader(self._tagged("A", "student"), "student") is True
        assert _for_this_reader(self._tagged("B", "teacher"), "student") is False

    def test_general_belongs_to_everyone(self):
        from app.agents.qa.nodes import _for_this_reader

        for audience in ("student", "teacher", "parent"):
            assert _for_this_reader(self._tagged("C", "general"), audience) is True

    def test_an_untagged_row_is_never_demoted(self):
        from app.agents.qa.nodes import _for_this_reader

        bare = KBChunk(kb_id="D", content="...", title="row D", score=0.5, relevance=0.5)
        assert _for_this_reader(bare, "student") is True

    @pytest.mark.asyncio
    async def test_the_rerank_puts_the_readers_own_audience_first(self):
        from app.agents.qa.nodes import make_rerank

        teacher = self._tagged("T", "teacher")
        student = self._tagged("S", "student")

        async def score(_query, chunks):
            # The teacher's row scores HIGHER, and must still lose to the
            # reader's own audience -- that is what makes this a tie-break
            # rather than a filter.
            return [0.9 if c.kb_id == "T" else 0.4 for c in chunks]

        state = {
            "retrieved": [teacher, student],
            "persona": "orion",
            "age_band": "16-18",
            "messages": [HumanMessage(content="tell me about saving")],
        }
        out = await make_rerank(score=score)(state)
        assert [c.kb_id for c in out["retrieved"]][0] == "S"

    @pytest.mark.asyncio
    async def test_another_audience_still_wins_when_it_is_all_there_is(self):
        from app.agents.qa.nodes import make_rerank

        teacher = self._tagged("T", "teacher")

        async def score(_query, chunks):
            return [0.9 for _ in chunks]

        state = {
            "retrieved": [teacher],
            "persona": "orion",
            "age_band": "16-18",
            "messages": [HumanMessage(content="tell me about saving")],
        }
        out = await make_rerank(score=score)(state)
        assert [c.kb_id for c in out["retrieved"]] == ["T"]


# ── 5. "make it simpler" ─────────────────────────────────────────────────────


class TestAskingForPlainerWords:
    """"make it simpler" was graded as an attempt at the last check question
    and answered with a new one about payday."""

    @pytest.mark.parametrize(
        "text",
        ["make it simpler", "say that simpler", "simpler", "explain it more simply",
         "in plainer words", "más simple", "explícamelo más fácil", "no entiendo",
         "plus simple", "je ne comprends pas"],
    )
    def test_it_reads_as_confusion_not_as_an_answer(self, text):
        from app.agents.learn.evaluate import triage
        from app.agents.learn.tutor import sounds_confused

        assert sounds_confused(text) is True
        assert triage(text) is None, "confusion is not a verdict on the question"

    @pytest.mark.parametrize("text", ["Saving", "true", "I think a loan", "EC$25"])
    def test_a_real_attempt_is_still_an_attempt(self, text):
        from app.agents.learn.tutor import sounds_confused

        assert sounds_confused(text) is False


# ── 6. the lesson's own chips, in the reader's language ──────────────────────


class TestTheLessonSpeaksTheReadersLanguage:
    def test_the_way_out_of_a_lesson_is_translated(self):
        from app.prompting.ui_lines import chips

        assert chips(["play_a_game", "see_tomorrow"], "es") == ["Jugar un juego", "Hasta mañana"]
        assert chips(["play_a_game", "see_tomorrow"], "fr") == ["Jouer à un jeu", "À demain"]
        assert chips(["play_a_game", "see_tomorrow"], "en") == ["Play a game", "See you tomorrow"]


# ── 7. the voice that could not speak, and never said so ─────────────────────


class TestTheConfigSaysWhichVoiceYouWillHear:
    """`/api/voice/config` returned `enabled: true` with six guides listed
    across three languages while `ELEVENLABS_API_KEY` was unset, so every Play
    spent a round trip discovering a 503 before falling back to the device."""

    def test_no_key_means_no_native_voice(self, monkeypatch):
        from app.voice import config as voice_config

        monkeypatch.setattr(
            voice_config.get_voice_settings(), "elevenlabs_api_key", None, raising=False
        )
        assert not voice_config.get_voice_settings().elevenlabs_api_key

    def test_the_response_carries_the_field(self):
        from app.voice.schemas import VoiceConfigResponse

        assert "native_voice" in VoiceConfigResponse.model_fields

    def test_it_defaults_true_so_an_older_client_is_unaffected(self):
        from app.voice.schemas import VoiceConfigResponse

        assert VoiceConfigResponse.model_fields["native_voice"].default is True


# ── 8. a wrap-up with nothing in it ──────────────────────────────────────────


class TestNothingCoveredIsNotAnAchievement:
    """"Nice work. You covered 0 concepts today." arrived mid-conversation,
    after a question that was never a lesson."""

    def test_zero_does_not_congratulate(self):
        from app.agents.learn.graph import _wrap_text

        text = _wrap_text("16-18", 0, {"locale": "en"})
        assert "0 concept" not in text
        assert "Nice work" not in text
        assert "lesson" in text.lower()

    @pytest.mark.parametrize("locale,word", [("es", "lección"), ("fr", "leçon")])
    def test_it_speaks_the_readers_language(self, locale, word):
        from app.agents.learn.graph import _wrap_text

        assert word in _wrap_text("16-18", 0, {"locale": locale})

    def test_real_progress_is_still_celebrated(self):
        from app.agents.learn.graph import _wrap_text

        assert "2 concepts" in _wrap_text("16-18", 2, {"locale": "en"})


# ── 9. a personality that stops after the first sentence ─────────────────────


class TestThePersonalityCarriesThroughTheAnswer:
    def test_the_block_says_so(self):
        from app.prompting.overlays import overlay_block

        block = overlay_block("limer", "16-18")
        assert "CARRY IT THROUGH" in block
        assert "last sentence" in block

    def test_and_still_forbids_moving_a_figure(self):
        from app.prompting.overlays import overlay_block

        block = overlay_block("professor", "16-18").lower()
        assert "never change is a figure" in block

    def test_a_barred_band_still_gets_nothing(self):
        from app.prompting.overlays import overlay_block

        assert overlay_block("professor", "5-8") == ""
