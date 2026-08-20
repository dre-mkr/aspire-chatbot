"""Launching a real game, and reacting to the score it comes back with."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from app.graph.state import band_index
from app.learning.mastery import Evidence, MasteryStore
from app.schemas.directives import GameDirective, directive_payload

from app.agents.learn.state import band_of

logger = logging.getLogger(__name__)

GameName = Literal["scramble", "true_false", "millionaire", "hangman"]

#: The youngest band each game is offered to.
#:
#: A game absent from this table is never offered by `available_for`, which is
#: how `millionaire` came to be a name in four type unions that nothing could
#: reach. Adding a game means adding a row here.
BAND_MIN: dict[str, str] = {
    "true_false": "5-8",
    "scramble": "9-12",
    # Reading a four-line question and holding four options in mind at once is
    # the barrier here, not the money in them.
    "millionaire": "9-12",
    # Spelling is the whole game, so the youngest band plays it -- with its own
    # word bank of four-letter words rather than a shortened version of Zion's.
    "hangman": "5-8",
}

#: The game module's own identifiers, which differ from the directive's names.
ENGINE_NAME: dict[str, str] = {
    "scramble": "word_scramble",
    "true_false": "true_false",
    "millionaire": "millionaire",
    "hangman": "hangman",
}


def persona_plays(persona: str | None) -> bool:
    """Whether this persona is offered games at all.

    The band gate and the engine's persona gate used to disagree, and the reader
    paid for it: `available_for` admits every band, so a card was opened for a
    guardian or a teacher, and then `GameEngine.start` refused the same request
    with `not_available_for_persona` and the card sat dead on the page.

    Aurora and Nova are written around programme information and teaching
    material rather than child activities, so the honest answer is that the card
    should never have been offered. An unknown persona is treated as playing, so
    a missing value degrades to the previous behaviour rather than to silence.
    """
    from app.games.models import PLAYING_PERSONAS, Persona

    name = (persona or "").strip().lower()
    if not name:
        return True
    try:
        return Persona(name) in PLAYING_PERSONAS
    except ValueError:
        return True


def available_for(age_band: str, persona: str | None = None) -> list[str]:
    """Which games this reader may be offered, youngest-appropriate first."""
    if not persona_plays(persona):
        return []
    index = band_index(age_band)
    if index < 0:
        return []
    return [
        game
        for game, minimum in BAND_MIN.items()
        if band_index(minimum) <= index
    ]


def permitted(game: str, age_band: str, persona: str | None = None) -> bool:
    return game in available_for(age_band, persona)


@dataclass(frozen=True, slots=True)
class GameResult:
    """What comes back when the component finishes."""

    game: str
    concept_id: str
    score: int
    max_score: int
    duration_s: int
    completed: bool

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> "GameResult | None":
        if not isinstance(payload, dict):
            return None
        game = payload.get("game")
        concept = payload.get("concept_id")
        if not isinstance(game, str) or not isinstance(concept, str):
            return None
        try:
            return cls(
                game=game,
                concept_id=concept,
                score=int(payload.get("score") or 0),
                max_score=max(1, int(payload.get("max_score") or 1)),
                duration_s=int(payload.get("duration_s") or 0),
                completed=bool(payload.get("completed", False)),
            )
        except (TypeError, ValueError):
            return None

    @property
    def fraction(self) -> float:
        return self.score / self.max_score


def launch_game(
    game: GameName,
    concept_id: str,
    difficulty: Literal[1, 2, 3] = 1,
    *,
    age_band: str,
    persona: str | None = None,
) -> dict[str, Any] | None:
    """The `game` directive to render, or None if the band or persona bars it."""
    if not permitted(game, age_band, persona):
        logger.info(
            "Declining %s for the %s band / %s persona; offering %s instead.",
            game,
            age_band,
            persona or "unknown",
            available_for(age_band, persona),
        )
        return None

    directive = GameDirective(
        game=game,
        concept=concept_id,
        difficulty=difficulty,
    )
    logger.info(
        "launch_game game=%s concept=%s difficulty=%d band=%s",
        game,
        concept_id,
        difficulty,
        age_band,
    )
    return directive_payload(directive)


# ── reacting to the result ───────────────────────────────────────────────────


def reaction_for(result: GameResult, band: str) -> str:
    """What the agent says, containing the child's actual score."""
    score, total = result.score, result.max_score

    if not result.completed:
        return (
            f"You got {score} before we stopped. Want to pick it up again, or "
            "carry on with the lesson?"
        )

    if result.fraction >= 0.8:
        if band == "5-8":
            return f"{score} out of {total}! You knew those."
        return f"{score} out of {total}. You have that one."

    if result.fraction >= 0.5:
        if band == "5-8":
            return f"{score} out of {total}. Good going -- let us look at the tricky ones."
        return (
            f"{score} out of {total}. Solid. The ones you missed are the ones "
            "worth going over."
        )

    if band == "5-8":
        return f"You got {score}. That one was tricky! Let us do it together."
    return (
        f"{score} out of {total} -- that set was a hard one. Let us go back over "
        "it and try again after."
    )


async def record_result(
    result: GameResult,
    *,
    learner_id: str | None,
    store: MasteryStore | None = None,
    age_band: str = "9-12",
) -> None:
    """Feed the score into mastery as EXPOSURE."""
    try:
        await (store or MasteryStore()).record(
            learner_id, result.concept_id, Evidence.GAME, age_band=age_band
        )
    except Exception:
        # As in `widget_result`: the score is on screen, so a bookkeeping failure must not undo it.
        logger.warning(
            "Could not record game mastery for concept %s.",
            result.concept_id,
            exc_info=True,
        )
    logger.info(
        "game_result game=%s concept=%s score=%d/%d completed=%s",
        result.game,
        result.concept_id,
        result.score,
        result.max_score,
        result.completed,
    )


def make_game_result_node(store: MasteryStore | None = None):
    """The node that runs when a game finishes."""

    async def game_result(state: Any) -> dict[str, Any]:
        from langchain_core.messages import AIMessage

        payload = (state.get("safety_flags") or {}).get("game_result")
        result = GameResult.parse(payload or {})
        if result is None:
            return {}

        band = band_of(state)
        # None for an anonymous visitor.
        learner = state.get("user_id") or None
        await record_result(result, learner_id=learner, store=store, age_band=band)

        return {
            "messages": [AIMessage(content=reaction_for(result, band))],
            "quick_replies": _chips(band),
            # Keep the learning agent the router picked; hardcoding `learn_agent` broke stickiness.
            "active_agent": state.get("active_agent") or "learn_agent",
            "learning": _learning_after(state, result),
        }

    return game_result


#: Below this fraction, a game result is evidence the concept has not landed.
STRUGGLED_BELOW = 0.5


def _learning_after(state: Any, result: GameResult) -> dict[str, Any]:
    """What the tutor's next turn should know about this score.

    §11. A game is retrieval practice under a scoreboard, and its result is the
    cleanest evidence the tutor gets. It was being written to the mastery scale
    and thrown away everywhere else, so a learner could score 2 out of 10 and
    the next turn would carry on as though nothing had been observed.
    """
    from app.agents.learn.state import merge, touched, wrong_again

    learning = state.get("learning") or {}
    concept_id = result.concept_id
    struggled = result.completed and result.fraction < STRUGGLED_BELOW

    return merge(
        learning,
        active_concept_id=concept_id,
        resolution_source="game",
        concepts_touched=touched(learning, concept_id),
        turns_since_check=0,
        awaiting_check_answer=False,
        pending_check_id=None,
        # A poor score is a miss on this concept, and it counts towards the
        # step-back threshold exactly as a wrong check answer would.
        wrong_by_concept=(
            wrong_again(learning, concept_id) if struggled else learning.get("wrong_by_concept") or {}
        ),
        # So the next teaching turn comes at it differently rather than
        # re-running the explanation that preceded the score. The strategy rung
        # is kept where it is precisely so that turn advances FROM it.
        teaching_strategy=str(learning.get("teaching_strategy") or "") if struggled else "",
        reteach_pending=struggled,
    )


def _chips(band: str) -> list[str]:
    if band == "5-8":
        return ["Again", "Back to lesson"]
    return ["Play again", "Back to the lesson"]
