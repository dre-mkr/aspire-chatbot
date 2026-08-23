"""A persona is a voice; a band is a reading level. They are not the same axis."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.curriculum.schema import PERSONA_KEYS, Lesson, load_all

BASE = dict(
    id="l99_x", module_id="module_01_saving", concept_id="save", order=1,
    objective="x",
    teach_points={"5-8": ["a coin"], "adult": ["put money aside"]},
    examples={"5-8": ["b"]},
    check_questions=[{"id": "q1_k", "prompt": {"5-8": "p"}, "options": ["Saving", "Spending"], "answer": 0}],
)


class TestTheKeysAreKeys:
    def test_they_match_the_access_matrix(self):
        """Duplicated rather than imported, so this is what stops it drifting."""
        from app.graph.access import PERSONAS

        assert set(PERSONA_KEYS) == set(PERSONAS)

    @pytest.mark.parametrize("label", ["Imani", "Azuri", "Skye", "Zion", "Guest"])
    def test_a_display_label_is_refused(self, label):
        """"Stella" was renamed to "Skye" while the key stayed `stella`.

        A lesson keyed on a display name would have been orphaned by that
        rename with nothing anywhere to say so.
        """
        with pytest.raises(ValidationError, match="unknown persona key"):
            Lesson(**BASE, persona_voice={label: {"teach_points": ["x"]}})

    @pytest.mark.parametrize("key", PERSONA_KEYS)
    def test_every_real_key_is_accepted(self, key):
        assert Lesson(**BASE, persona_voice={key: {"teach_points": ["x"]}})


class TestPersonaFirstThenBand:
    def test_a_voice_wins_over_the_band_map(self):
        lesson = Lesson(**BASE, persona_voice={"aurora": {"teach_points": ["her words"]}})
        assert lesson.teach_for("adult", "aurora") == ["her words"]

    def test_without_a_voice_the_band_still_answers(self):
        lesson = Lesson(**BASE, persona_voice={"aurora": {"teach_points": ["her words"]}})
        assert lesson.teach_for("adult", "nova") == ["put money aside"]

    def test_no_persona_at_all_is_the_old_behaviour(self):
        assert Lesson(**BASE).teach_for("adult") == ["put money aside"]

    def test_an_empty_voice_does_not_shadow_the_band(self):
        """A voice authored with only a joke must not blank the teaching."""
        lesson = Lesson(**BASE, persona_voice={"aurora": {"joke": "ha"}})
        assert lesson.teach_for("adult", "aurora") == ["put money aside"]

    def test_the_shape_is_always_a_list(self):
        """The persona layer must not make callers handle two return types."""
        lesson = Lesson(**BASE, persona_voice={"aurora": {"teach_points": ["x"]}})
        for got in (lesson.teach_for("adult", "aurora"), lesson.teach_for("adult", "nova"),
                    lesson.examples_for("5-8", "stella"), lesson.examples_for("5-8")):
            assert isinstance(got, list)

    def test_a_joke_never_falls_back(self):
        """Skye's joke in Azuri's mouth would be worse than no joke."""
        lesson = Lesson(**BASE, persona_voice={"stella": {"joke": "clink"}})
        assert lesson.joke_for("stella") == "clink"
        assert lesson.joke_for("nova") is None
        assert lesson.joke_for(None) is None


class TestTheBudgetingLessonIsAuthoredForAllSix:
    """`l05_a_simple_plan` is the worked example the rest are backfilled against."""

    @pytest.fixture(scope="class")
    def lesson(self):
        return load_all().lessons["l05_a_simple_plan"]

    def test_every_persona_has_a_voice(self, lesson):
        assert set(lesson.persona_voice) == set(PERSONA_KEYS)

    def test_the_band_map_now_reaches_adult(self, lesson):
        """Without this key an adult falls to 16-18, then 13-15 -- the Imani bug."""
        assert "adult" in lesson.teach_points

    @pytest.mark.parametrize(
        ("persona", "band"),
        [("stella", "5-8"), ("kaleb", "9-12"), ("orion", "13-15"),
         ("aurora", "adult"), ("nova", "adult"), ("guest", "adult")],
    )
    def test_each_voice_clears_the_gates(self, lesson, persona, band):
        from app.graph.nodes.safety_out import cap_for, word_count
        from app.safety import vocab

        body = " ".join(lesson.teach_for(band, persona) + lesson.examples_for(band, persona))
        assert body, f"{persona} has no words"
        assert not vocab.check(body + " " + (lesson.joke_for(persona) or ""), band, teaching_scope=True)
        cap = cap_for(band, "learn_agent")
        assert cap is None or word_count(body) <= cap

    def test_the_three_adults_are_actually_different(self, lesson):
        """They share a band. If they share words too, the split bought nothing."""
        said = {p: tuple(lesson.teach_for("adult", p)) for p in ("aurora", "nova", "guest")}
        assert len(set(said.values())) == 3
