"""The release checker's own logic, which nothing else would catch.

The tool talks to a live server, so its network path is exercised by running
it. What is worth pinning here is the part that gives ADVICE: a checker that
tells an operator to set a variable this server reads for nothing is worse than
no checker, because they will set it, restart, and see no change.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools" / "voice_check.py"
_spec = importlib.util.spec_from_file_location("voice_check", _PATH)
voice_check = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(voice_check)


def _result(persona: str, language: str, status: str) -> dict:
    return {"persona": persona, "language": language, "status": status}


class TestTheCastingAdviceNamesRealVariables:
    def test_english_asks_for_the_base_id_not_a_suffix(self):
        """`VOICE_KALEB_EN` is read by nothing. The base is `VOICE_KALEB`."""
        advice = voice_check._casting_advice(
            [
                _result("kaleb", "en", voice_check.UNCAST),
                _result("kaleb", "es", voice_check.UNAVAILABLE),
                _result("kaleb", "fr", voice_check.UNAVAILABLE),
            ]
        )
        joined = " ".join(advice)
        assert "VOICE_KALEB=" in joined
        assert "VOICE_KALEB_EN" not in joined

    def test_one_missing_language_asks_for_that_override(self):
        advice = " ".join(
            voice_check._casting_advice(
                [
                    _result("stella", "en", voice_check.OK),
                    _result("stella", "es", voice_check.UNCAST),
                    _result("stella", "fr", voice_check.OK),
                ]
            )
        )
        assert "VOICE_STELLA_ES=" in advice
        assert "VOICE_STELLA=" not in advice

    def test_a_guide_uncast_everywhere_asks_for_the_base_once(self):
        advice = voice_check._casting_advice(
            [
                _result("nova", "en", voice_check.UNCAST),
                _result("nova", "es", voice_check.UNCAST),
                _result("nova", "fr", voice_check.UNCAST),
            ]
        )
        bases = [line for line in advice if line.startswith("VOICE_NOVA=")]
        assert len(bases) == 1, "one variable covers all three languages"

    def test_it_always_ends_by_saying_to_restart(self):
        advice = voice_check._casting_advice([_result("orion", "fr", voice_check.UNCAST)])
        assert "restart" in advice[-1]


class TestItKnowsAudioFromAnApology:
    @pytest.mark.parametrize("magic", [b"ID3\x04", b"\xff\xfb\x90", b"\xff\xf3\x00"])
    def test_an_mp3_is_audio(self, magic):
        assert magic.startswith(voice_check.MP3_MAGIC)

    @pytest.mark.parametrize("body", [b'{"detail":"no"}', b"<html>", b""])
    def test_anything_else_is_not(self, body):
        assert not body.startswith(voice_check.MP3_MAGIC)


class TestEveryShippedLanguageHasALine:
    def test_three_languages_three_lines(self):
        assert set(voice_check.LINES) == {"en", "es", "fr"}
        for language, line in voice_check.LINES.items():
            assert line.strip(), language
            # Short on purpose: a liveness check, not a listening test.
            assert len(line) < 80, language

    def test_the_showcase_subset_is_covered_by_those_lines(self):
        for _persona, language in voice_check.SHOWCASE:
            assert language in voice_check.LINES
