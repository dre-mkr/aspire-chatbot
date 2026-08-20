"""The game engine: state, scoring and correctness."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, replace
from datetime import date

from app.games.config import GameSettings, get_game_settings
from app.games.events import (
    GAME_COMPLETED,
    GAME_STARTED,
    HINT_USED,
    WORD_SKIPPED,
    WORD_SOLVED,
    EventSink,
    GameEvent,
    get_sink,
)
from app.games.models import (
    PLAYING_PERSONAS,
    Closing,
    Entry,
    GameSession,
    GameState,
    HintResult,
    Language,
    Persona,
    Prompt,
    SkipResult,
    SubmitResult,
    Summary,
)
from app.games.protocol import Game
from app.games.scramble import get_word_scramble
from app.games.store import SessionStore, get_store
from app.games.truefalse import get_true_false

logger = logging.getLogger(__name__)

# Emitted when an item resolves against the player.
WORD_MISSED = "word_missed"


# --- Failures the agent is expected to handle -----------------------------


class GameError(Exception):
    """Base for conditions the tools turn into a declined response."""

    reason = "game_error"


class GameNotRunning(GameError):
    reason = "no_game_running"


class GameAlreadyRunning(GameError):
    reason = "already_running"


class UnknownGameType(GameError):
    reason = "unknown_game"


class NoContentAvailable(GameError):
    reason = "no_set_for_language"


class PersonaNotEligible(GameError):
    reason = "not_available_for_persona"


class HintsNotAvailable(GameError):
    """This game has no hints to give."""

    reason = "hints_not_available"


@dataclass(frozen=True, slots=True)
class StartResult:
    game_type: str
    display_name: str
    prompt: Prompt


@dataclass(frozen=True, slots=True)
class GameInfo:
    game_type: str
    display_name: str
    items: int
    supports_hints: bool
    languages: list[str]


class GameEngine:
    def __init__(
        self,
        games: list[Game] | None = None,
        store: SessionStore | None = None,
        sink: EventSink | None = None,
        settings: GameSettings | None = None,
        today: date | None = None,
    ) -> None:
        self._settings = settings or get_game_settings()
        self._games = {
            g.game_type: g
            for g in (games or [get_word_scramble(), get_true_false()])
        }
        self._store = store or get_store()
        self._sink = sink or get_sink()
        # Injectable so the volatility tests can age content without waiting.
        self._today = today

    # --- helpers ----------------------------------------------------------

    def _game(self, game_type: str) -> Game:
        try:
            return self._games[game_type]
        except KeyError:
            raise UnknownGameType(f"No game called {game_type!r}.") from None

    def _session(self, session_id: str) -> GameSession:
        session = self._store.get(session_id)
        if session is None:
            raise GameNotRunning("No game is running in this conversation.")
        return session

    def _emit(self, session: GameSession, event: str, **data: object) -> None:
        self._sink.emit(
            GameEvent(
                event=event,
                session_id=session.session_id,
                game_type=session.game_type,
                language=session.language.value,
                persona=session.persona.value if session.persona else None,
                elapsed_seconds=time.time() - session.started_at,
                data=dict(data),
            )
        )

    def _current(self, session: GameSession) -> Entry:
        game = self._game(session.game_type)
        entry_id = session.current_entry_id
        if entry_id is None:
            raise GameNotRunning("This game has already finished.")
        return game.entry(entry_id)

    def _prompt_for_current(self, session: GameSession) -> Prompt | None:
        if session.finished:
            return None
        game = self._game(session.game_type)
        return game.prompt(
            self._current(session), session.index + 1, len(session.order)
        )

    def _closing(self, session: GameSession) -> Closing | None:
        """The set's own last word, looked up when the round ends."""
        game = self._games.get(session.game_type)
        if game is None:
            return None
        for game_set in game.sets_for(session.language):
            if game_set.id == session.set_id:
                return game_set.closing
        return None

    def _finish(self, session: GameSession, reason: str) -> Summary:
        summary = replace(session.summarise(), closing=self._closing(session))
        self._emit(
            session,
            GAME_COMPLETED,
            reason=reason,
            solved=summary.solved,
            missed=summary.missed,
            skipped=summary.skipped,
            total=summary.total,
            hints_used=summary.hints_used,
            duration_seconds=summary.duration_seconds,
        )
        self._store.delete(session.session_id)
        return summary

    def _servable(self, entries: tuple[Entry, ...], persona: Persona | None) -> list[Entry]:
        """Items this player may be served, right now."""
        today = self._today or date.today()
        return [
            entry
            for entry in entries
            if (persona is None or persona in entry.persona_bands)
            and entry.servable_on(today, review_days=self._settings.volatile_review_days)
        ]

    # --- operations -------------------------------------------------------

    def list_games(self, language: Language = Language.EN) -> list[GameInfo]:
        infos: list[GameInfo] = []
        for game in self._games.values():
            languages = [lang.value for lang in Language if game.sets_for(lang)]
            sets = game.sets_for(language)
            available = sum(len(self._servable(s.entries, None)) for s in sets)
            items = min(game.round_size, available) if game.round_size else available
            infos.append(
                GameInfo(
                    game_type=game.game_type,
                    display_name=game.display_name,
                    items=items,
                    supports_hints=game.supports_hints,
                    languages=languages,
                )
            )
        return infos

    def start(
        self,
        session_id: str,
        game_type: str = "word_scramble",
        language: Language = Language.EN,
        persona: Persona | None = None,
    ) -> StartResult:
        # Games are a learning activity for account holders.
        if persona is not None and persona not in PLAYING_PERSONAS:
            raise PersonaNotEligible(
                f"Games are for account holders; {persona.value} is not one."
            )

        if self._store.get(session_id) is not None:
            raise GameAlreadyRunning("A game is already running here.")

        game = self._game(game_type)
        sets = game.sets_for(language)
        if not sets:
            raise NoContentAvailable(
                f"No {game_type} set has been authored in {language.value} yet."
            )

        # Every set with something servable for this player, in filename order.
        #
        # This used to stop at the first set, which made the pool exactly as big
        # as one file and made filename order decide the whole game. Content was
        # then unreachable by construction: a second set for the same persona
        # could never be played, so "add more questions" had nowhere to put them.
        #
        # `Game.entry()` resolves an id against every set it loaded, not against
        # one set, so an order that spans files is already a supported shape.
        # The first contributing set names the round -- it is what `_closing`
        # looks up -- which keeps the ECCB warm-up leading for the child bands.
        # A caller who named no persona is the exception, and gets the first set
        # alone as before. `_servable(entries, None)` matches every entry, so
        # merging there would hand an unidentified player every persona's bank at
        # once -- a five-year-old's words and a teenager's in one round.
        game_set = None
        servable: list[Entry] = []
        for candidate in sets:
            items = self._servable(candidate.entries, persona)
            if not items:
                continue
            if game_set is None:
                game_set = candidate
            servable.extend(items)
            if persona is None:
                break

        if game_set is None:
            raise NoContentAvailable(
                "Nothing in this game can be served right now — check persona "
                "bands and whether volatile items still have a recent "
                "verified_on date."
            )

        if game.round_size:
            # Shuffled per session, and only then stored.
            rng = random.Random(f"{session_id}:{game_set.id}")
            chosen = rng.sample(servable, min(game.round_size, len(servable)))
            order = tuple(entry.id for entry in chosen)
        else:
            # The ECCB handout is a printed sequence; the chat game keeps it.
            order = tuple(entry.id for entry in servable)

        session = GameSession(
            session_id=session_id,
            game_type=game_type,
            set_id=game_set.id,
            language=language,
            persona=persona,
            order=order,
        )
        self._store.put(session)
        self._emit(session, GAME_STARTED, set_id=game_set.id, total=len(order))

        prompt = self._prompt_for_current(session)
        assert prompt is not None  # a session always starts with an item
        return StartResult(
            game_type=game.game_type,
            display_name=game.display_name,
            prompt=prompt,
        )

    def submit(self, session_id: str, answer: str) -> SubmitResult:
        session = self._session(session_id)
        entry = self._current(session)
        game = self._game(session.game_type)

        verdict = game.check(entry, answer)

        # Unreadable is not wrong.
        if verdict is None:
            return SubmitResult(
                correct=False,
                attempts=session.attempts,
                unreadable=game.unreadable_message(answer),
            )

        session.attempts += 1
        attempts_taken = session.attempts
        hints_taken = session.hints_used.get(entry.id, 0)

        if not verdict and not game.advance_on_wrong:
            self._store.put(session)
            # No echo of the answer and no "close!" — a near-miss signal narrows the item.
            return SubmitResult(correct=False, attempts=attempts_taken)

        # From here the item resolves either way, and the cursor moves in the same call.
        reveal = game.reveal(entry)

        if verdict:
            self._emit(
                session,
                WORD_SOLVED,
                entry_id=entry.id,
                position=session.index + 1,
                attempts=attempts_taken,
                hints_used=hints_taken,
                first_try=attempts_taken == 1 and hints_taken == 0,
            )
            session.solved.append(entry.id)
        else:
            self._emit(
                session,
                WORD_MISSED,
                entry_id=entry.id,
                position=session.index + 1,
                attempts=attempts_taken,
            )
            session.missed.append(entry.id)

        session.advance()

        if session.finished:
            summary = self._finish(session, reason="completed")
            return SubmitResult(
                correct=verdict,
                attempts=attempts_taken,
                teaching_note=game.teaching(entry),
                reveal=reveal,
                finished=True,
                summary=summary,
            )

        self._store.put(session)
        return SubmitResult(
            correct=verdict,
            attempts=attempts_taken,
            teaching_note=game.teaching(entry),
            reveal=reveal,
            next_prompt=self._prompt_for_current(session),
        )

    def hint(self, session_id: str) -> HintResult:
        session = self._session(session_id)
        game = self._game(session.game_type)

        # Declined by the game, not special-cased here.
        if not game.supports_hints:
            raise HintsNotAvailable(
                f"{game.display_name} does not have hints — there is no clue to "
                "give on a true-or-false statement that is not the answer."
            )

        entry = self._current(session)
        session.hint_level += 1
        level = session.hint_level

        # Past the last rung, asking again means the child has had enough, so reveal instead.
        if level > self._settings.max_hint_level:
            return self._give_up(session, entry, reason="revealed")

        session.hints_used[entry.id] = session.hints_used.get(entry.id, 0) + 1
        self._store.put(session)
        self._emit(session, HINT_USED, entry_id=entry.id, level=level)
        return HintResult(text=game.hint(entry, level), level=level)

    def skip(self, session_id: str) -> SkipResult:
        session = self._session(session_id)
        entry = self._current(session)
        outcome = self._give_up(session, entry, reason="skipped")
        assert outcome.reveal is not None
        return SkipResult(
            reveal=outcome.reveal,
            next_prompt=outcome.next_prompt,
            finished=outcome.finished,
            summary=outcome.summary,
        )

    def _give_up(self, session: GameSession, entry: Entry, *, reason: str) -> HintResult:
        """Reveal the answer and advance, in one step."""
        game = self._game(session.game_type)
        self._emit(
            session,
            WORD_SKIPPED,
            entry_id=entry.id,
            reason=reason,
            hints_used=session.hints_used.get(entry.id, 0),
            attempts=session.attempts,
        )
        session.skipped.append(entry.id)
        session.advance()

        reveal = game.reveal(entry)

        if session.finished:
            summary = self._finish(session, reason="completed")
            return HintResult(
                text="", level=0, reveal=reveal, finished=True, summary=summary
            )

        self._store.put(session)
        return HintResult(
            text="",
            level=0,
            reveal=reveal,
            next_prompt=self._prompt_for_current(session),
        )

    def quit(self, session_id: str) -> Summary:
        session = self._session(session_id)
        return self._finish(session, reason="quit")

    def is_running(self, session_id: str) -> bool:
        return self._store.get(session_id) is not None

    def state(self, session_id: str) -> GameState | None:
        """The running game, or None."""
        session = self._store.get(session_id)
        if session is None or session.finished:
            return None

        game = self._game(session.game_type)
        entry = self._current(session)
        prompt = game.prompt(entry, session.index + 1, len(session.order))
        hints = (
            tuple(
                game.hint(entry, level)
                for level in range(
                    1, min(session.hint_level, self._settings.max_hint_level) + 1
                )
            )
            if game.supports_hints
            else ()
        )

        return GameState(
            game_type=game.game_type,
            display_name=game.display_name,
            prompt=prompt,
            supports_hints=game.supports_hints,
            hint_level=session.hint_level,
            max_hint_level=self._settings.max_hint_level if game.supports_hints else 0,
            hints=hints,
            attempts=session.attempts,
            solved=len(session.solved),
            skipped=len(session.skipped) + len(session.missed),
            total=len(session.order),
            language=session.language,
            persona=session.persona,
        )


_engine: GameEngine | None = None


def get_engine() -> GameEngine:
    global _engine
    if _engine is None:
        _engine = GameEngine()
    return _engine


def set_engine(engine: GameEngine | None) -> None:
    """Swap the engine. Used by tests."""
    global _engine
    _engine = engine
