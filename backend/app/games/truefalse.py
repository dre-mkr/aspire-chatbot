"""True or false: judge a statement, then read why.

From ECCB's own quiz bank. The verdict is the hook; the explanation is the
reason the game exists, and it is reproduced verbatim rather than written here
or regenerated at runtime.

Three things this game does differently from the scramble, all of them declared
through the protocol rather than special-cased by the engine:

- **No hints.** A hint on a binary choice is the answer. `supports_hints` is
  False and the engine declines the request before this module is reached.
- **A round, not the bank.** Eighteen statements with multi-paragraph
  explanations is not a warm-up. Five, shuffled per session.
- **An answer can be unreadable.** `yes` and `no` are refused rather than
  guessed at, because on a negatively-framed statement they genuinely do not say
  which way the player meant.
"""

from __future__ import annotations

from functools import lru_cache

from app.games.config import GameSettings, get_game_settings
from app.games.loader import TRUE_FALSE, load_sets
from app.games.models import (
    Entry,
    GameSet,
    Language,
    Prompt,
    PromptKind,
    Reveal,
    StatementEntry,
)
from app.games.normalise import looks_like_yes_no, parse_verdict

TRUE_LABEL = "True"
FALSE_LABEL = "False"


class TrueFalseGame:
    """Judge a statement true or false, then read ECCB's explanation."""

    game_type = TRUE_FALSE
    display_name = "True or False"

    # A hint here would be the answer. There is no middle rung on a coin flip.
    supports_hints = False

    # Warm-up length. The bank is eighteen and the explanations are long; nobody
    # sits through that, and the teaching lands better five at a time.
    round_size = 5

    # Re-asking a true/false is just waiting for the coin to land the other way.
    # A wrong answer shows ECCB's explanation and the round moves on — the
    # teaching is the point, not the score.
    advance_on_wrong = True

    def __init__(self, settings: GameSettings | None = None) -> None:
        self._settings = settings or get_game_settings()
        self._by_language = load_sets(
            self._settings.resolved(self._settings.seed_dir), game_type=TRUE_FALSE
        )
        self._entries: dict[str, StatementEntry] = {
            entry.id: entry
            for sets in self._by_language.values()
            for game_set in sets
            for entry in game_set.entries
            if isinstance(entry, StatementEntry)
        }

    # --- content ----------------------------------------------------------

    def sets_for(self, language: Language) -> list[GameSet]:
        # Drafts are loaded and validated, never played.
        return [s for s in self._by_language.get(language, []) if not s.draft]

    def entry(self, entry_id: str) -> StatementEntry:
        return self._entries[entry_id]

    # --- rules ------------------------------------------------------------

    def prompt(self, entry: Entry, position: int, total: int) -> Prompt:
        assert isinstance(entry, StatementEntry)
        return Prompt(
            kind=PromptKind.STATEMENT,
            text=entry.statement,
            position=position,
            total=total,
            choices=(TRUE_LABEL, FALSE_LABEL),
        )

    def check(self, entry: Entry, answer: str) -> bool | None:
        assert isinstance(entry, StatementEntry)
        verdict = parse_verdict(answer)
        if verdict is None:
            # Unreadable, not wrong. The engine leaves the statement open.
            return None
        return verdict is entry.answer

    def unreadable_message(self, answer: str) -> str:
        if looks_like_yes_no(answer):
            return (
                "I am not sure which way you mean — on a statement like this, "
                '"yes" could mean either. Say true or false.'
            )
        return 'Say true or false, or just T or F.'

    def reveal(self, entry: Entry) -> Reveal:
        assert isinstance(entry, StatementEntry)
        return Reveal(
            answer=TRUE_LABEL if entry.answer else FALSE_LABEL,
            explanation=entry.explanation,
            takeaway=entry.takeaway,
            paragraphs=entry.paragraphs,
            bullets=entry.bullets,
            after=entry.after,
            topic=entry.topic,
            topic_line=entry.topic_line,
        )

    def teaching(self, entry: Entry) -> str:
        """ECCB's own words, unchanged. This is the whole point of the game."""
        assert isinstance(entry, StatementEntry)
        return entry.explanation

    def hint(self, entry: Entry, level: int) -> str:
        # Unreachable: `supports_hints` is False, so the engine refuses first.
        raise NotImplementedError("True or false does not offer hints.")


@lru_cache(maxsize=1)
def get_true_false() -> TrueFalseGame:
    """Process-wide instance. Seeds are read once, at first use."""
    return TrueFalseGame()
