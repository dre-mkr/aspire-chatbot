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

GameName = Literal["scramble", "true_false", "millionaire"]

#: The youngest band each game is offered to.
BAND_MIN: dict[str, str] = {
    "true_false": "5-8",
    "scramble": "9-12",
}

#: The game module's own identifiers, which differ from the directive's names.
ENGINE_NAME: dict[str, str] = {
    "scramble": "word_scramble",
    "true_false": "true_false",
    "millionaire": "millionaire",
}


def available_for(age_band: str) -> list[str]:
    """Which games this band may be offered, youngest-appropriate first."""
    index = band_index(age_band)
    if index < 0:
        return []
    return [
        game
        for game, minimum in BAND_MIN.items()
        if band_index(minimum) <= index
    ]


def permitted(game: str, age_band: str) -> bool:
    return game in available_for(age_band)


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
) -> dict[str, Any] | None:
    """The `game` directive for the client to render, or None if the band bars it."""
    if not permitted(game, age_band):
        logger.info(
            "Declining %s for the %s band; offering %s instead.",
            game,
            age_band,
            available_for(age_band),
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
        # Same rule as `widget_result`: the score is already on screen, and a bookkeeping failure must not take it away.
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
            # Keep whichever learning agent the router picked for this caller; hardcoding `learn_agent` broke stickiness fo…
            "active_agent": state.get("active_agent") or "learn_agent",
        }

    return game_result


def _chips(band: str) -> list[str]:
    if band == "5-8":
        return ["Again", "Back to lesson"]
    return ["Play again", "Back to the lesson"]
