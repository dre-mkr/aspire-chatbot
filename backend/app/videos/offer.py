"""Whether this finished turn should end by offering a video.

Called from `safety_out`, which is where every turn converges no matter which
agent answered it. That placement is the whole point: the first version of this
hung off the QA agent, and the client's own example -- "What does scarcity
mean?" -- is answered by the tutor, so the offer never appeared. Anything that
hangs off one agent is a feature that works for some questions and silently does
not for others.

Runs after the answer exists and can never change it. The turn has already been
generated, grounded, cited, capped and stripped by the time this is asked.
"""

from __future__ import annotations

import logging
from typing import Any

from app.domain import Language, Persona
from app.videos.catalog import chip_for, relevant_to

logger = logging.getLogger(__name__)

#: Turns that already ARE something, and must not also be an offer.
#:
#: A game, an eligibility check, a sign-up form or a video already playing is a
#: turn with one job. Appending "would you like to watch a video?" to a form is
#: how an assistant starts talking over itself.
_CARD_TURNS_TAKE_NO_OFFER = True


def offer_for(state: Any, question: str) -> tuple[str, str] | None:
    """`(video id, the chip that offers it)`, or None -- which is the usual answer.

    The chip is phrased as an invitation and kept deliberately short, because it
    is also what gets SENT when it is tapped, and `wants_video` refuses anything
    longer than a command. "Would you like to watch a short video about
    scarcity?" reads better and would arrive as an eleven-word question that
    opens nothing.
    """
    if not question.strip():
        return None

    flags = state.get("safety_flags") or {}
    # Already a card, or the turn that just opened the player.
    if _CARD_TURNS_TAKE_NO_OFFER and flags.get("card"):
        return None
    # A widget result or a graded game answer is a continuation, not a question.
    if any(flags.get(name) for name in ("widget_interaction", "game_result")):
        return None
    # Never offer twice running. The reader has one in front of them already.
    if state.get("offered_video"):
        return None

    persona_key = state.get("persona")
    locale = state.get("locale") or "en"
    try:
        video = relevant_to(
            question,
            persona=Persona(persona_key) if persona_key else None,
            language=Language(locale),
        )
    except ValueError:
        # An unrecognised persona or locale is not a reason to spoil a turn that
        # has already been answered.
        logger.debug("video offer skipped: unknown persona %r or locale %r", persona_key, locale)
        return None

    if video is None:
        return None
    # Once per conversation. A reader who did not take the offer has answered
    # it, and a second identical offer three questions later is the assistant
    # not listening -- which is the one thing the brief asks this not to be.
    if video.id in set(state.get("videos_offered") or ()):
        return None
    # In the reader's language. The chip's text is also what gets SENT when it
    # is tapped, so an English chip in a French conversation both reads as an
    # afterthought and -- if the wording drifts from `_WATCH` -- opens nothing.
    return video.id, chip_for(video, Language(locale))
