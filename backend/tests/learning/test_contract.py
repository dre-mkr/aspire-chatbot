"""What a lesson must BE, as a predicate rather than as an adjective in a prompt."""

from __future__ import annotations

import pytest

from app.agents.learn.contract import (
    BLOCKING,
    CONTRACTS,
    check_lesson,
    contract_for,
    longest_sentence_words,
    tts_safe,
    word_count,
)
from app.graph.nodes.safety_out import LESSON_WORD_CAPS, WORD_CAPS, cap_for


class TestTheTablesAgree:
    def test_the_two_cap_tables_agree(self):
        """`contract.max_words` and `safety_out.LESSON_WORD_CAPS` are one number."""
        for band, contract in CONTRACTS.items():
            assert LESSON_WORD_CAPS[band] == contract.max_words, (
                f"{band}: the prompt asks for at most {contract.max_words} words and "
                f"the outbound gate permits {LESSON_WORD_CAPS[band]}. Every lesson turn "
                "at this band would be re-prompted."
            )

    def test_every_band_has_a_contract(self):
        assert set(CONTRACTS) == set(WORD_CAPS)
        assert set(CONTRACTS) == set(LESSON_WORD_CAPS)

    def test_the_floor_is_below_the_ceiling_everywhere(self):
        for band, contract in CONTRACTS.items():
            assert contract.min_words < contract.max_words, band

    def test_a_lesson_cap_is_never_below_a_chat_cap(self):
        """Teaching is allowed more room than chatting, never less."""
        for band in CONTRACTS:
            chat = WORD_CAPS[band]
            lesson = LESSON_WORD_CAPS[band]
            if chat is not None and lesson is not None:
                assert lesson >= chat, band

    def test_the_lesson_floor_exceeds_the_old_chat_ceiling_at_5_8(self):
        """The specific number this workstream changed, pinned so it cannot revert."""
        assert CONTRACTS["5-8"].min_words > WORD_CAPS["5-8"]

    def test_cap_for_selects_by_agent(self):
        from app.graph.nodes.safety_out import QA_WORD_CAPS

        assert cap_for("5-8", "learn_agent") == LESSON_WORD_CAPS["5-8"]
        # A factual answer gets its own, roomier table: a cited answer cut mid-rule is wrong, not short.
        assert cap_for("5-8", "qa_agent") == QA_WORD_CAPS["5-8"]
        assert cap_for("adult", "qa_agent") is None
        assert cap_for("5-8", None) == WORD_CAPS["5-8"]
        # All three learning names, not just the one.
        for name in ("learn_agent", "learning_preview", "learning_sample"):
            assert cap_for("9-12", name) == LESSON_WORD_CAPS["9-12"]


def a_lesson(words: int, *, question: bool = True, sentence_words: int = 8) -> str:
    """A lesson of exactly `words` words, in sentences of `sentence_words`."""
    parts: list[str] = []
    remaining = words - (7 if question else 0)
    while remaining > 0:
        take = min(sentence_words, remaining)
        parts.append(" ".join(["money"] * take) + ".")
        remaining -= take
    if question:
        parts.append("How much do you have now, then?")
    return " ".join(parts)


class TestTheCheck:
    def test_a_lesson_at_the_floor_passes(self):
        contract = contract_for("9-12")
        result = check_lesson(a_lesson(contract.min_words + 5), band="9-12")
        assert result.ok, result.quoted()

    def test_a_lesson_below_the_floor_is_blocking(self):
        result = check_lesson(a_lesson(20), band="9-12")
        assert not result.ok
        assert not result.servable, "a thin lesson is worth a regeneration"
        assert any(v.code == "TOO_SHORT" for v in result.violations)

    def test_the_violation_names_the_number(self):
        """"Be more thorough" moves a word count by 10%. A number fixes it."""
        result = check_lesson(a_lesson(20), band="9-12")
        detail = result.quoted()
        assert "60" in detail, "the band's floor must be quoted back"

    def test_empty_prose_is_blocking(self):
        result = check_lesson("", band="9-12")
        assert not result.servable
        assert result.violations[0].code == "EMPTY"

    def test_no_question_is_blocking(self):
        result = check_lesson(a_lesson(80, question=False), band="9-12")
        assert not result.servable
        assert any(v.code == "NO_QUESTION" for v in result.violations)

    def test_two_questions_is_blocking(self):
        """A lesson with two questions asks a child to choose which to answer."""
        text = a_lesson(80) + " And what do you think about that?"
        result = check_lesson(text, band="9-12")
        assert not result.servable
        assert any(v.code == "TOO_MANY_QUESTIONS" for v in result.violations)

    def test_an_over_long_sentence_is_advisory_not_blocking(self):
        """The split is a cost decision, made deliberately."""
        result = check_lesson(a_lesson(80, sentence_words=30), band="9-12")
        assert not result.ok
        assert result.servable
        assert any(v.code == "SENTENCE_TOO_LONG" for v in result.violations)

    def test_ungrounded_prose_is_blocking(self):
        """A lesson using none of the concept's own words was not written from it."""
        result = check_lesson(
            a_lesson(80), band="9-12", grounding_terms=("compound", "interest")
        )
        assert not result.servable
        assert any(v.code == "UNGROUNDED" for v in result.violations)

    def test_grounded_prose_passes(self):
        text = a_lesson(75) + " " + "That is compound interest."
        result = check_lesson(
            text, band="9-12", grounding_terms=("compound", "interest")
        )
        assert not any(v.code == "UNGROUNDED" for v in result.violations)

    def test_markup_is_advisory(self):
        result = check_lesson("# Heading\n\n" + a_lesson(80), band="9-12")
        assert any(v.code == "MARKUP" for v in result.violations)
        assert result.servable

    def test_a_list_is_permitted_for_older_readers_only(self):
        text = a_lesson(150) + "\n- one\n- two"
        assert any(v.code == "MARKUP" for v in check_lesson(text, band="13-15").violations)
        assert not any(v.code == "MARKUP" for v in check_lesson(text, band="16-18").violations)

    def test_every_blocking_code_is_reachable(self):
        """A code in `BLOCKING` that no check can produce is a dead branch."""
        produced = set()
        for text, band, terms in (
            ("", "9-12", ()),
            (a_lesson(20), "9-12", ()),
            (a_lesson(80, question=False), "9-12", ()),
            (a_lesson(80) + " Really?", "9-12", ()),
            (a_lesson(80), "9-12", ("compound",)),
        ):
            for violation in check_lesson(text, band=band, grounding_terms=terms).violations:
                produced.add(violation.code)
        assert BLOCKING <= produced


class TestMeasurement:
    def test_word_count_matches_safety_out(self):
        from app.graph.nodes.safety_out import word_count as gate_count

        for text in ("", "one", "one two three", "  spaced   out  "):
            assert word_count(text) == gate_count(text)

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Short. Longer sentence here now.", 4),
            ("One two three four five six seven.", 7),
            ("", 0),
        ],
    )
    def test_longest_sentence(self, text, expected):
        assert longest_sentence_words(text) == expected


class TestTTS:
    """A voice reads "EC$25" as "E C dollar sign twenty five"."""

    @pytest.mark.parametrize(
        "written,spoken",
        [
            ("You have EC$25 saved.", "You have 25 EC dollars saved."),
            ("It pays 3% a year.", "It pays 3 percent a year."),
            ("Save (or spend) it.", "Save it."),
            ("Rice & peas", "Rice and peas"),
            ("yes/no", "yes or no"),
        ],
    )
    def test_substitutions(self, written, spoken):
        assert tts_safe(written) == spoken

    def test_it_is_a_rendering_not_a_regeneration(self):
        """The screen and the audio are one lesson said two ways."""
        text = "Put EC$100 in at 3% and you have EC$103."
        assert tts_safe(text) != text
        assert "103" in tts_safe(text)
        assert "EC dollars" in tts_safe(text)
