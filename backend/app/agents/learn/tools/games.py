"""Launching a real game, and reacting to the score it comes back with.

A game is never simulated in text. Not "usually not" -- never. The three game
components already exist, own their own server-side session, and grade a tapped
answer without a model round trip; this tool says WHICH to render and nothing
else.

That constraint is what keeps the answer out of the chat response.
`tests/games/test_no_answer_leak.py` exists because a `game_started` payload
with a free-form dict in it would satisfy nothing and could carry anything, and
the same rule applies here: `GameDirective` has no field a puzzle or a solution
could travel in.

## Band gating

    millionaire   13 and up
    scramble      7 and up  -- so the top of the 5-8 band, and up
    true_false    every band

`scramble` at 7 is the awkward one, because the bands are 5-8 rather than 5-6
and 7-8. The rule is applied to the band: a 5-8 learner is NOT offered scramble,
because the band contains five-year-olds and offering a spelling game to a
five-year-old who cannot yet spell is the failure worth avoiding. A seven-year-
old loses a game they would have enjoyed; that is the cheaper mistake.

## A game score never reaches mastery 3

`Evidence.GAME` saturates at 1, exactly like a widget interaction. A game score
mixes understanding, reading speed and luck, and letting one push a concept to
"mastered" would make the scale mean "played a game". `mastery.apply` enforces
it; this module records the evidence and does not decide what it is worth.

## The agent must react to the ACTUAL score

`reaction_for` builds a sentence containing the numbers the child produced.
"Well done!" after a game is the same nothing as "Well done!" after a widget --
and children read a generic response as not having been watched.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from app.graph.state import band_index
from app.learning.mastery import Evidence, MasteryStore
from app.schemas.directives import GameDirective, directive_payload

logger = logging.getLogger(__name__)

GameName = Literal["scramble", "true_false", "millionaire"]

#: The youngest band each game is offered to. See the module docstring for why
#: `scramble` is 9-12 rather than "7+".
BAND_MIN: dict[str, str] = {
    "true_false": "5-8",
    "scramble": "9-12",
    "millionaire": "13-15",
}

#: The game module's own identifiers, which differ from the directive's names.
#: One mapping, here, rather than the two spellings drifting apart across the
#: codebase.
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
    """What comes back when the component finishes.

    Carries the score and nothing about the puzzle. A result that included the
    questions would put them in the transcript, and the transcript is read back
    into the model on later turns.
    """

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
    """The `game` directive for the client to render, or None if the band bars it.

    None rather than an exception: a learning agent that tried to start
    millionaire for a nine-year-old should carry on teaching, not fail the turn.
    The refusal is logged so the prompt that produced it can be fixed.
    """
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
    """What the agent says, containing the child's actual score.

    Three bands of response and none of them is a verdict. A low score gets
    "that one was hard" rather than anything a child could read as a judgement
    of them -- the same rule the hint ladder holds, for the same reason.
    """
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
    """Feed the score into mastery as EXPOSURE.

    `Evidence.GAME` and not `Evidence.CORRECT`, even on a perfect score. A game
    is a recall exercise with a timer and multiple choice; a check question with
    no hints is the evidence that moves the scale, and this is not that.
    """
    try:
        await (store or MasteryStore()).record(
            learner_id, result.concept_id, Evidence.GAME, age_band=age_band
        )
    except Exception:
        # Same rule as `widget_result`: the score is already on screen, and a
        # bookkeeping failure must not take it away.
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
    """The node that runs when a game finishes.

    Same shape as `widget_result`: the result arrives as a flag on state, the
    agent responds IN THE SAME TURN with the actual numbers, and mastery
    records exposure.
    """

    async def game_result(state: Any) -> dict[str, Any]:
        from langchain_core.messages import AIMessage

        payload = (state.get("safety_flags") or {}).get("game_result")
        result = GameResult.parse(payload or {})
        if result is None:
            return {}

        band = str(state.get("age_band") or "9-12")
        # None for an anonymous visitor. `MasteryStore.record` accepts it and
        # writes nothing -- see `mastery.is_persistable`.
        learner = state.get("user_id") or None
        await record_result(result, learner_id=learner, store=store, age_band=band)

        return {
            "messages": [AIMessage(content=reaction_for(result, band))],
            "quick_replies": _chips(band),
            "active_agent": "learn_agent",
        }

    return game_result


def _chips(band: str) -> list[str]:
    if band == "5-8":
        return ["Again", "Back to lesson"]
    return ["Play again", "Back to the lesson"]
