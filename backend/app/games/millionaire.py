"""Who Wants to Be a Millionaire: four choices, one right, a ladder to climb."""

from __future__ import annotations

from functools import lru_cache

from app.games.config import GameSettings, get_game_settings
from app.games.loader import MILLIONAIRE, load_sets
from app.games.models import (
    Entry,
    GameSet,
    Language,
    Prompt,
    PromptKind,
    QuizEntry,
    Reveal,
)
from app.games.normalise import normalise

#: What the player has to be at, for the piggy bank to be full.
#:
#: Five is the round, not a target to grind towards. The format is a ladder the
#: player walks up in one sitting; a hundred questions would be a quiz bank with
#: a piggy bank drawn on it.
ROUND_SIZE = 5


class MillionaireGame:
    """Answer four-choice questions and fill the piggy bank.

    The name was already in `directives.py`, in `intents.py`, in the frontend's
    directive union and in `learn/tools/games.py` before any of this existed --
    so asking to play it produced a directive that rendered the word scramble
    and then a 422 from an engine that had never heard of it. This is that bug's
    other half.
    """

    game_type = MILLIONAIRE
    display_name = "Who Wants to Be a Millionaire?"

    # The choices are the hint. A nudge on top of four options is the answer.
    supports_hints = False

    round_size = ROUND_SIZE

    # A ladder only goes one way. Re-asking a question whose four options are
    # still on screen is offering a second guess at a three-way choice.
    advance_on_wrong = True

    def __init__(self, settings: GameSettings | None = None) -> None:
        self._settings = settings or get_game_settings()
        self._by_language = load_sets(
            self._settings.resolved(self._settings.seed_dir), game_type=MILLIONAIRE
        )
        self._entries: dict[str, QuizEntry] = {
            entry.id: entry
            for sets in self._by_language.values()
            for game_set in sets
            for entry in game_set.entries
            if isinstance(entry, QuizEntry)
        }

    # --- content ----------------------------------------------------------

    def sets_for(self, language: Language) -> list[GameSet]:
        # Drafts are loaded and validated, never played.
        return [s for s in self._by_language.get(language, []) if not s.draft]

    def entry(self, entry_id: str) -> QuizEntry:
        return self._entries[entry_id]

    # --- rules ------------------------------------------------------------

    def prompt(self, entry: Entry, position: int, total: int) -> Prompt:
        assert isinstance(entry, QuizEntry)
        # `choices` and nothing else. `answer_index` stays on this side.
        return Prompt(
            kind=PromptKind.QUIZ,
            text=entry.question,
            position=position,
            total=total,
            choices=entry.choices,
        )

    def check(self, entry: Entry, answer: str) -> bool | None:
        """Accept the option's text, its letter, or its number.

        A tapped button sends the text. A child typing into the composer sends
        "B", or "2", or the answer in their own words -- and being told "I did
        not understand" for typing the right answer is the game breaking, not
        the player getting it wrong.
        """
        assert isinstance(entry, QuizEntry)
        said = normalise(answer)
        if not said:
            return None

        # The text of one of the options.
        for index, choice in enumerate(entry.choices):
            if said == normalise(choice):
                return index == entry.answer_index

        # A letter: a, b, c, d.
        if len(said) == 1 and "a" <= said <= "d":
            return (ord(said) - ord("a")) == entry.answer_index

        # A number: 1..4.
        if said.isdigit() and 1 <= int(said) <= len(entry.choices):
            return (int(said) - 1) == entry.answer_index

        # Not readable as a choice. The engine leaves the question open rather
        # than spending the player's one attempt on a typo.
        return None

    def unreadable_message(self, answer: str) -> str:
        return "Tap one of the four answers, or type its letter — A, B, C or D."

    def reveal(self, entry: Entry) -> Reveal:
        assert isinstance(entry, QuizEntry)
        return Reveal(
            answer=entry.answer,
            explanation=entry.explanation,
            topic=entry.topic,
        )

    def teaching(self, entry: Entry) -> str:
        assert isinstance(entry, QuizEntry)
        return entry.explanation

    def hint(self, entry: Entry, level: int) -> str:
        # Unreachable: `supports_hints` is False, so the engine refuses first.
        raise NotImplementedError("Millionaire does not offer hints.")


@lru_cache(maxsize=1)
def get_millionaire() -> MillionaireGame:
    """Process-wide instance. Seeds are read once, at first use."""
    return MillionaireGame()
