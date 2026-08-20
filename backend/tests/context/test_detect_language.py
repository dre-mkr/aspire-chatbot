"""The switch that lets a reader change language mid-conversation.

Every case here is deterministic on purpose: the detector makes no model call,
so there is nothing to mock and nothing that can answer differently tomorrow.

The expensive mistakes are in `TestWhatMustNeverMoveTheLanguage`. Switching
when the reader did not ask costs them the eligibility card, the sign-up chips
and the refusal text in a language they did not choose -- so a false positive is
worse here than a missed switch, and the bar is set accordingly.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.graph.nodes.detect_language import (
    LOCALES,
    MIN_WORDS,
    asked_for,
    detect,
    detect_language,
    switched_to,
    words,
)
from app.graph.state import initial_state


def _state(text: str, *, locale: str = "en", override: str | None = None):
    """A turn whose latest human message is `text`."""
    state = initial_state(
        session_id="s-1",
        user_id="u-1",
        device_id="d-1",
        persona="stella",
        age_band="9-12",
        account_status="beneficiary",
        locale=locale,  # type: ignore[arg-type]
    )
    state["messages"] = [HumanMessage(content=text)]
    state["locale_override"] = override  # type: ignore[typeddict-item]
    return state


class TestSomebodyAsksForALanguage:
    """Honoured however short the message -- "en francais" is not ambiguous."""

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("hablame en espanol", "es"),
            ("háblame en español", "es"),
            ("en francais", "fr"),
            ("en français s'il vous plaît", "fr"),
            ("speak english please", "en"),
            ("can you speak French?", "fr"),
            ("¿puedes hablar español?", "es"),
            ("switch to english", "en"),
        ],
    )
    def test_the_named_language_wins(self, message, expected):
        assert asked_for(message) == expected
        assert switched_to(message) == expected

    def test_a_request_beats_the_language_it_is_written_in(self):
        """A Spanish sentence asking for English is a request for English."""
        assert asked_for("por favor hablame en ingles") == "en"

    def test_naming_two_languages_is_not_a_request(self):
        """That is a sentence about languages, not an instruction."""
        assert asked_for("do you speak english or spanish") is None

    def test_a_language_name_alone_is_not_a_request(self):
        assert asked_for("spanish") is None


class TestSomebodyJustSwitches:
    """Detected from the prose, at four words or more, one language winning clearly."""

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("Hola, quiero saber como puedo abrir una cuenta para mi hija", "es"),
            ("¿Quién puede abrir una cuenta?", "es"),
            ("Necesito ayuda con el dinero de mi hijo", "es"),
            ("Bonjour, je voudrais savoir comment ouvrir un compte", "fr"),
            ("Qui peut ouvrir un compte pour ma fille?", "fr"),
            ("How much money can I save each month", "en"),
        ],
    )
    def test_the_prose_decides(self, message, expected):
        assert detect(message) == expected

    def test_the_word_floor_is_four(self):
        assert MIN_WORDS == 4

    def test_three_spanish_words_are_not_enough(self):
        """One clause below the floor, the same clause above it."""
        assert detect("quiero una cuenta") is None
        assert detect("quiero abrir una cuenta") == "es"

    def test_accents_count_as_evidence(self):
        assert detect("¿Cuántos años necesita mi hija?") == "es"

    def test_every_detected_value_is_a_locale_the_product_has_copy_for(self):
        for message in ("Hola, quiero abrir una cuenta", "je voudrais ouvrir un compte"):
            assert detect(message) in LOCALES


class TestWhatMustNeverMoveTheLanguage:
    """Each of these is an expensive mistake, and each one is a test."""

    @pytest.mark.parametrize(
        "message",
        ["ok", "si", "oui", "yes please", "thanks", "ok thanks", "no", "si por favor"],
    )
    def test_too_short_to_judge(self, message):
        """`si` is Spanish for yes and an English typo for `is`."""
        assert switched_to(message) is None

    def test_a_figure_has_no_words_in_it(self):
        assert words("EC$500") == ["ec"]
        assert switched_to("EC$500") is None

    def test_a_name_is_not_a_language(self):
        assert switched_to("Stella") is None

    def test_one_borrowed_word_is_not_a_switch(self):
        """This must stay English."""
        assert detect("What is the dinero limit for a new account") == "en"

    def test_a_borrowed_word_does_not_move_an_english_session(self):
        assert detect_language(_state("What is the dinero limit for a new account")) == {}

    def test_an_empty_message_changes_nothing(self):
        assert detect_language(_state("   ")) == {}


class TestTheNodeWritesTheSwitch:
    def test_it_sets_both_the_locale_and_the_override(self):
        update = detect_language(_state("hablame en espanol"))
        assert update == {"locale_override": "es", "locale": "es"}

    def test_an_english_session_asking_for_english_moves_nothing(self):
        assert detect_language(_state("speak english please")) == {}

    def test_a_spanish_session_can_switch_back(self):
        update = detect_language(_state("speak english please", locale="es", override="es"))
        assert update == {"locale_override": "en", "locale": "en"}

    def test_it_switches_on_the_prose_alone(self):
        update = detect_language(_state("¿Quién puede abrir una cuenta?"))
        assert update["locale"] == "es"

    def test_it_reads_the_latest_human_message_only(self):
        """Not the assistant's reply, and not an earlier turn."""
        state = _state("ok")
        state["messages"] = [
            HumanMessage(content="hablame en espanol"),
            AIMessage(content="Claro, puedo ayudarte."),
            HumanMessage(content="ok"),
        ]
        assert detect_language(state) == {}


class TestTheOverrideSurvivesHydrate:
    """`hydrate` rewrites `locale` from the token every turn. This puts it back.

    Without it a Spanish session flips back to English on the very next message,
    which is the whole reason the field exists.
    """

    def test_it_re_applies_an_earlier_switch(self):
        update = detect_language(_state("ok", locale="en", override="es"))
        assert update == {"locale": "es"}

    def test_it_does_not_rewrite_the_override_it_is_holding(self):
        """Nothing new was asked for, so only `locale` moves."""
        assert "locale_override" not in detect_language(_state("ok", locale="en", override="es"))

    def test_holding_is_a_no_op_once_the_locale_already_agrees(self):
        assert detect_language(_state("ok", locale="es", override="es")) == {}

    def test_a_short_message_cannot_undo_a_switch(self):
        """"si" in a Spanish session stays Spanish -- it is not evidence of English."""
        assert detect_language(_state("si", locale="es", override="es")) == {}

    def test_a_new_switch_replaces_the_old_one(self):
        update = detect_language(_state("en francais", locale="es", override="es"))
        assert update == {"locale_override": "fr", "locale": "fr"}

    def test_the_field_starts_empty(self):
        assert _state("hi")["locale_override"] is None
