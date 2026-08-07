"""A widget interaction is a TURN, and the agent must answer it.

    "Whoa -- you found it. EC$5 a week for five years, and the bank added
     EC$180 on top. You didn't work for that EC$180. That's compound interest."

That sentence is the whole point of the widget system. Without it a widget is
wallpaper: something that moved on screen and then the conversation carried on
as though it had not.

## Always the specific numbers, never generic praise

"Great job!" tells a child nothing and they know it. The reply has to contain
the figures THEY produced, because those figures are the evidence that the thing
they just did meant something.

The numbers come from the server, recomputed here from the interaction's final
state through `formulas.registry`. The client sends what it computed too, and
that value is used only to notice a disagreement -- the client is display, the
server is the authority, and a mismatch is a parity bug worth a log line.

## An allocator is never graded

`no_wrong_answer` is fixed True on that schema for exactly this reason. The
reply names the TRADE-OFF the child chose -- "you kept more than you spent, so
the bicycle arrives sooner and the snow cones are fewer" -- and never says
whether it was right, because it was a values question and there is no right.

## Skipping is silence

A widget the child never touched produces no interaction event at all, so this
node never runs, and the agent carries on without comment. No guilt, no nagging,
no "you didn't try the slider".

## Mastery moves 0 to 1 and no further

Enforced in `learning/mastery.py`, not here. This node records the evidence and
the scale decides what it is worth -- which is exposure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage

from app.graph.state import AspireState
from app.learning.mastery import Evidence, MasteryStore
from app.widgets.formulas import registry

from app.agents.learn.state import band_of

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Interaction:
    """What the client reported. Mirrors `emitInteraction.ts`."""

    widget_kind: str
    concept_id: str
    final_state: dict[str, Any]
    computed: dict[str, Any]
    attempts: int = 1
    dwell_ms: int = 0
    completed: bool = True

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> "Interaction | None":
        """Read an interaction, or None if it is not one.

        Returns None rather than raising: this arrives from a browser, and a
        malformed body is a client bug or a probe, neither of which should be a
        500.
        """
        if not isinstance(payload, dict):
            return None
        kind = payload.get("widget_kind")
        concept = payload.get("concept_id")
        if not isinstance(kind, str) or not isinstance(concept, str):
            return None
        return cls(
            widget_kind=kind,
            concept_id=concept,
            final_state=payload.get("final_state") or {},
            computed=payload.get("computed") or {},
            attempts=int(payload.get("attempts") or 1),
            dwell_ms=int(payload.get("dwell_ms") or 0),
            completed=bool(payload.get("completed", True)),
        )


def recompute(interaction: Interaction) -> dict[str, Any]:
    """The figures, computed here rather than trusted from the client.

    The client's own numbers are compared against these and a difference is
    logged. It is not an error -- the reply uses the server's figures either
    way -- but a divergence means the TypeScript mirror has drifted from the
    Python registry, and the parity test should have caught it.
    """
    state = interaction.final_state

    if interaction.widget_kind == "growth_stack":
        result = registry.compound_interest(
            int(state.get("principal_cents", 0)),
            int(state.get("contribution_cents", 0)),
            float(state.get("rate", 0.0)),
            int(state.get("periods", 0) or 0),
            1,
        )
        return {
            "total": result.value,
            "total_display": result.display,
            "saved": result.breakdown["contributed"],
            "saved_display": result.breakdown["contributed_display"],
            "earned": result.breakdown["earned"],
            "earned_display": result.breakdown["earned_display"],
        }

    if interaction.widget_kind == "simulator":
        # The formula the widget named is not in the interaction payload, so the
        # client's computed value is what there is. It has already been through
        # the parity test; this path exists so a simulator's reply is still
        # specific rather than generic.
        return dict(interaction.computed)

    return dict(interaction.computed)


# ── what the agent says ──────────────────────────────────────────────────────


def _growth_stack_reply(figures: dict[str, Any], band: str) -> str:
    saved = figures.get("saved_display", "")
    earned = figures.get("earned_display", "")
    if band == "9-12":
        return (
            f"Look at that. You put in {saved}, and the bank added {earned} on "
            f"top. You did not work for that {earned} -- it came from leaving "
            "your money alone."
        )
    return (
        f"There it is: {saved} of your own money, and {earned} that the account "
        f"produced. That second number is what compounding does, and it grows "
        "faster the longer you leave it."
    )


def _simulator_reply(
    interaction: Interaction, figures: dict[str, Any], band: str
) -> str:
    display = figures.get("display") or figures.get("total_display") or ""
    settings = ", ".join(
        f"{key.replace('_', ' ')} {value}"
        for key, value in list(interaction.final_state.items())[:3]
    )
    if not display:
        return f"You set {settings}. What made the biggest difference?"
    return f"With {settings}, you get {display}. Try moving one and see which one matters most."


def _allocator_reply(interaction: Interaction, band: str) -> str:
    """Names the trade-off. Never says whether the split was right.

    `no_wrong_answer` is fixed True on the allocator schema so that this branch
    cannot be reached for a widget the agent might grade -- and this function
    contains no comparison, no "but", and no better/worse.
    """
    parts = {
        key: value
        for key, value in interaction.final_state.items()
        if isinstance(value, (int, float))
    }
    if not parts:
        return "That is your split. It says something about what matters to you."

    biggest = max(parts, key=lambda key: parts[key])
    smallest = min(parts, key=lambda key: parts[key])
    if biggest == smallest:
        return "You split it evenly. That is a choice too -- a bit of everything."

    if band == "5-8":
        return (
            f"You put the most into {biggest.replace('_', ' ')} and the least "
            f"into {smallest.replace('_', ' ')}. That means more of that thing, "
            "sooner."
        )
    return (
        f"Most of it went to {biggest.replace('_', ' ')} and least to "
        f"{smallest.replace('_', ' ')}. That is the trade: more of the first "
        "now, less of the second. Both are real."
    )


def _proportion_reply(interaction: Interaction, band: str) -> str:
    highlighted = interaction.final_state.get("highlighted")
    total = interaction.final_state.get("total")
    if highlighted is None or total is None:
        return "You counted them. That is the share we were talking about."
    return f"{highlighted} out of {total}. That is the part you keep."


def reply_for(interaction: Interaction, figures: dict[str, Any], band: str) -> str:
    """The agent's response, always carrying the child's own numbers."""
    if interaction.widget_kind == "growth_stack":
        return _growth_stack_reply(figures, band)
    if interaction.widget_kind == "simulator":
        return _simulator_reply(interaction, figures, band)
    if interaction.widget_kind == "allocator":
        return _allocator_reply(interaction, band)
    if interaction.widget_kind == "proportion":
        return _proportion_reply(interaction, band)
    if interaction.widget_kind == "compare":
        revealed = sum(1 for value in interaction.final_state.values() if value)
        return (
            f"You looked at {revealed} of them. The difference between those two "
            "is the whole idea."
            if revealed
            else "Have a look at both before you decide."
        )
    if interaction.widget_kind == "reveal_cards":
        turned = sum(1 for value in interaction.final_state.values() if value)
        return f"You turned over {turned}. Which one surprised you?"
    return "Good -- you had a go at it."


def make_widget_result(store: MasteryStore | None = None):
    """The node. Runs when an interaction arrives, and answers it in one turn."""

    async def widget_result(state: AspireState) -> dict[str, Any]:
        payload = (state.get("safety_flags") or {}).get("widget_interaction")
        interaction = Interaction.parse(payload or {})
        if interaction is None:
            return {}

        band = band_of(state)
        figures = recompute(interaction)

        # The client's own figure, compared but never used. A divergence is a
        # parity bug that `formulas.parity.test.ts` should have caught, and the
        # log line is how it gets noticed if it did not.
        claimed = interaction.computed.get("total") or interaction.computed.get("value")
        computed = figures.get("total")
        if claimed is not None and computed is not None and int(claimed) != int(computed):
            logger.warning(
                "Widget parity drift on %s: client said %s, server says %s.",
                interaction.widget_kind,
                claimed,
                computed,
            )

        # None for an anonymous visitor. `MasteryStore.record` accepts it and
        # writes nothing -- see `mastery.is_persistable`.
        learner = state.get("user_id") or None
        try:
            await (store or MasteryStore()).record(
                learner,
                interaction.concept_id,
                Evidence.WIDGET,
                age_band=band_of(state),
            )
        except Exception:
            # The reply is the point of this turn and it is already assembled.
            # Losing the mastery row costs a scheduling hint; raising costs the
            # child the answer about the numbers they just produced, and reads
            # as the assistant breaking because they touched something.
            logger.warning(
                "Could not record widget mastery for concept %s.",
                interaction.concept_id,
                exc_info=True,
            )

        logger.info(
            "widget_result kind=%s concept=%s dwell=%dms attempts=%d",
            interaction.widget_kind,
            interaction.concept_id,
            interaction.dwell_ms,
            interaction.attempts,
        )

        return {
            "messages": [AIMessage(content=reply_for(interaction, figures, band))],
            "quick_replies": _chips(band),
            "active_agent": "learn_agent",
        }

    return widget_result


def _chips(band: str) -> list[str]:
    if band == "5-8":
        return ["Again", "Next"]
    return ["Try it again", "Keep going"]
