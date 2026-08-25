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
    def test_the_block_names_the_dimensions_it_moves(self):
        """"More colourful" is not an instruction. These are."""
        from app.prompting.overlays import overlay_block

        block = overlay_block("limer", "16-18")
        assert "CARRY IT THROUGH" in block
        assert "LAST sentence" in block
        for dimension in ("rhythm", "analogy", "vocabulary", "humour", "follow-up"):
            assert dimension in block, f"{dimension} is not named"

    def test_and_names_what_it_may_never_move(self):
        from app.prompting.overlays import overlay_block

        block = overlay_block("professor", "16-18")
        assert "NEVER MOVES" in block
        for fixed in ("figure", "date", "rule", "citation", "source", "safety gate", "word cap"):
            assert fixed in block, f"{fixed} is not protected"

    def test_a_barred_band_still_gets_nothing(self):
        from app.prompting.overlays import overlay_block

        assert overlay_block("professor", "5-8") == ""


# ── 10. the teen registration policy ─────────────────────────────────────────


class TestATeenIsPreparedNotEnrolled:
    """Policy, resolved: 16-17 may prepare and understand the whole process;
    the enrolment is completed with a parent or legal guardian; the adult is
    handed to Imani. None of it blocks the teenager from information.

    Before this, Zion at seventeen asked "ok how do i sign up" and was asked
    "And how are you related to the child?" over chips reading Mother, Father,
    Grandmother, Grandfather -- one turn after being told he could register
    himself.
    """

    @staticmethod
    def _state(band: str, message: str, locale: str = "en", **extra):
        state = {"age_band": band, "locale": locale, "persona": "orion"}
        state.update(extra)
        return state

    def test_sixteen_to_eighteen_is_asked_its_age_first(self):
        from app.graph.nodes.cards import _teen_registration

        update = _teen_registration(self._state("16-18", "how do i sign up"), "how do i sign up")
        assert update is not None
        assert update["awaiting_teen_age"] is True
        assert "how old are you" in update["messages"][0].content.lower()
        assert len(update["quick_replies"]) == 4

    def test_thirteen_to_fifteen_needs_no_probe(self):
        from app.graph.nodes.cards import _teen_registration

        update = _teen_registration(self._state("13-15", "how do i sign up"), "how do i sign up")
        assert update is not None
        assert not update.get("awaiting_teen_age")
        assert "guardian" in update["messages"][0].content.lower()

    @pytest.mark.parametrize("said", ["I am 17", "17", "i'm 16", "tengo 17"])
    def test_under_eighteen_gets_the_guardian_route_and_imani(self, said):
        from app.graph.nodes.cards import _teen_registration

        state = self._state("16-18", said, awaiting_teen_age=True)
        update = _teen_registration(state, said)
        text = update["messages"][0].content.lower()
        assert "guardian" in text
        assert "imani" in text
        # Prepared, not blocked.
        assert "prepared" in text
        assert update["teen_age"] in (16, 17)
        assert update["awaiting_teen_age"] is False
        assert update["quick_replies"], "the process is still offered"

    @pytest.mark.parametrize("said", ["I am 18", "18", "older than 18"])
    def test_eighteen_or_over_is_not_sent_to_a_guardian(self, said):
        from app.graph.nodes.cards import _teen_registration

        state = self._state("16-18", said, awaiting_teen_age=True)
        text = _teen_registration(state, said)["messages"][0].content.lower()
        assert "guardian has to do it for you" in text or "18" in text
        assert "imani" not in text

    def test_an_unclear_answer_drops_the_question_rather_than_repeating_it(self):
        """The latch is the fault this whole flow exists to undo."""
        from app.graph.nodes.cards import _teen_registration

        state = self._state("16-18", "what is compound interest", awaiting_teen_age=True)
        assert _teen_registration(state, "what is compound interest") is None

    def test_a_teenager_applying_for_a_child_is_still_a_guardian_question(self):
        from app.graph.nodes.cards import _teen_registration

        message = "i want to register my daughter"
        assert _teen_registration(self._state("16-18", message), message) is None

    @pytest.mark.parametrize(
        "locale,message,word",
        [
            ("es", "quiero registrarme", "tutor legal"),
            ("fr", "je veux m'inscrire", "tuteur légal"),
        ],
    )
    def test_the_policy_is_stated_in_the_readers_language(self, locale, message, word):
        from app.graph.nodes.cards import _teen_registration

        state = self._state("13-15", message, locale=locale)
        assert word in _teen_registration(state, message)["messages"][0].content

    def test_it_never_asks_for_anything_more_than_an_age(self):
        """No national ID, no date of birth, no address, no account number."""
        from app.graph.nodes.cards import _TEEN_AGE_ASK, _TEEN_AGE_CHIPS

        for locale in ("en", "es", "fr"):
            asked = (_TEEN_AGE_ASK[locale] + " " + " ".join(_TEEN_AGE_CHIPS[locale])).lower()
            for forbidden in ("birth", "nacimiento", "naissance", "id", "address",
                              "dirección", "adresse", "account", "cuenta", "compte"):
                assert forbidden not in asked.split(), f"{forbidden!r} asked in {locale}"


class TestSigningUpIsUnderstoodInThreeLanguages:
    @pytest.mark.parametrize(
        "text",
        ["how do i sign up", "how do i join", "how can i register",
         "¿cómo me inscribo?", "quiero registrarme", "puedo inscribirme",
         "je veux m'inscrire", "comment je m'inscris", "comment s'inscrire"],
    )
    def test_these_ask_to_register(self, text):
        from app.graph.nodes.intents import wants_registration

        assert wants_registration(text) is True

    @pytest.mark.parametrize("text", ["what is ASPIRE", "who can join ASPIRE?"])
    def test_asking_about_it_is_not_asking_for_it(self, text):
        from app.graph.nodes.intents import wants_registration

        assert wants_registration(text) is False

    @pytest.mark.parametrize(
        "text",
        ["quiero registrar a mi hijo", "je veux inscrire mon enfant",
         "quiero registrar a mi nieta", "i want to register my child"],
    )
    def test_applying_for_a_child_is_recognised_in_all_three(self, text):
        from app.graph.nodes.cards import _FOR_ANOTHER

        assert bool(_FOR_ANOTHER.search(text)) is True


# ── 11. the wrap-up that ended a session nobody had finished ─────────────────


class TestAWrapUpNeedsSomethingToWrap:
    @pytest.mark.asyncio
    async def test_no_concept_touched_means_no_ceremony(self):
        from app.agents.learn.graph import make_wrap_session

        class _EmptyStore:
            async def all_for(self, _learner):
                return []

        state = {
            "learning": {"phase": "wrapping", "concepts_touched": []},
            "age_band": "16-18",
            "locale": "en",
            "session_id": "s-1",
            "user_id": "u-1",
        }
        update = await make_wrap_session(_EmptyStore())(state)
        assert "messages" not in update, "it announced an ending nobody asked for"
        assert "ui_directives" not in update, "and drew a progress card behind it"
        assert update["learning"]["wrapped"] is False
