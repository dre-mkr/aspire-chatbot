"""Kaleb and Skye are different personas, and the games knew it last.

WHAT WAS WRONG
    `_CONTENT_BANK` mapped Kaleb onto Stella, justified in a comment as: "every
    seed entry written for a 9-12 reader lists `stella` in its `persona_bands`,
    from when he was one." That was not true.

    Stella's bank is 5-8 material throughout. Its hangman words are MONEY, COIN,
    SAVE, SPEND, SHARE, BANK, GOAL, NEEDS -- which is `_ALLOW["5-8"]` word for
    word. And NOT ONE of the 158 seed entries carried an `age_bands` tag, so the
    band filter that was supposed to sort the older items out could never fire.

    A twelve-year-old was being asked to unscramble COIN and to answer "What is
    a bank?". Kaleb's card names that failure exactly:

        "IF the message reads CONFUSED -> change the EXAMPLE, not the
         vocabulary. Simplifying the words reads as a demotion and loses this
         reader."
        "Default to the OLDER end of this band. This reader is in secondary
         school."

    Giving him a key of his own was a change of vocabulary. This is the rest of
    it.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from app.domain import Persona
from app.games.engine import _CONTENT_BANK

_SEEDS = pathlib.Path(__file__).resolve().parents[2] / "app/games/seeds/en"


def _entries() -> list[dict]:
    out = []
    for path in sorted(_SEEDS.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for entry in data.get("entries", []) or []:
            entry = dict(entry)
            entry["_file"] = path.name
            out.append(entry)
    return out


class TestHeDoesNotBorrow:
    def test_kaleb_is_not_in_the_content_bank(self):
        assert Persona.KALEB not in _CONTENT_BANK, (
            "Kaleb is reading another persona's items again. If he has lost his "
            "own sets, restore them rather than pointing him at Stella's -- hers "
            "are written for a five-year-old."
        )

    def test_he_has_items_of_his_own(self):
        mine = [e for e in _entries() if "kaleb" in (e.get("persona_bands") or [])]
        assert mine, "no seed entry lists `kaleb`"
        assert len(mine) >= 10, f"only {len(mine)} items; a round needs a pool"

    def test_every_one_of_them_is_tagged_for_his_band(self):
        """The tag is what stops this silently reverting. An untagged item
        serves EVERY band, which is how Stella's 5-8 words reached him."""
        for entry in _entries():
            if "kaleb" in (entry.get("persona_bands") or []):
                assert entry.get("age_bands") == ["9-12"], (
                    f"{entry['_file']}:{entry.get('id')} is Kaleb's and carries "
                    f"age_bands={entry.get('age_bands')!r}"
                )


class TestHisItemsSoundLikeHim:
    """Not Skye's vocabulary with a different label on it."""

    #: The 5-8 allow-list. A bank made only of these is Skye's bank.
    YOUNGEST = {"SAVE", "SPEND", "SHARE", "MONEY", "BANK", "COIN", "GOAL", "WAIT"}

    def test_his_words_are_not_the_five_year_old_list(self):
        words = {
            str(e.get("word", "")).upper()
            for e in _entries()
            if "kaleb" in (e.get("persona_bands") or []) and e.get("word")
        }
        assert words, "no word-scramble items for Kaleb"
        assert not words <= self.YOUNGEST, (
            f"Kaleb's word bank is the 5-8 allow-list: {sorted(words)}"
        )

    def test_he_gets_the_terms_his_own_ladder_opens(self):
        """`interest`, `budget`, `deposit`, `earn` are permitted at 9-12 and are
        the point of the band. A bank that avoids them is pitched too young."""
        words = {
            str(e.get("word", "")).upper()
            for e in _entries()
            if "kaleb" in (e.get("persona_bands") or []) and e.get("word")
        }
        assert words & {"INTEREST", "BUDGET", "DEPOSIT", "EARN", "SAVINGS", "SHARES"}

    @pytest.mark.parametrize(
        "banned", ["compound", "inflation", "dividend", "portfolio", "loan"]
    )
    def test_and_none_his_ladder_still_closes(self, banned):
        from app.safety import vocab

        for entry in _entries():
            if "kaleb" not in (entry.get("persona_bands") or []):
                continue
            text = " ".join(
                str(entry.get(k, ""))
                for k in ("word", "hint", "definition", "statement",
                          "takeaway", "explanation", "topic_line")
            )
            found = {v.term for v in vocab.check(text, "9-12")}
            assert banned not in found, (
                f"{entry['_file']}:{entry.get('id')} uses {banned!r}, which the "
                f"9-12 gate strips -- the item would arrive with a hole in it"
            )


class TestTheTagIsWhatMakesFilteringPossible:
    def test_untagged_items_serve_every_band(self):
        """Documented behaviour, and the trap that caused this. Recorded so the
        next person tagging a bank knows an omission is not neutral."""
        from app.games.engine import GameEngine

        assert "serves every band" in (GameEngine._servable.__doc__ or "")
