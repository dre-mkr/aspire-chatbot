"""The Tin: the visible pile that only ever fills.

The landing has promised "earn coins as you go" since launch, and no coin
existed anywhere. The Tin is that promise kept: a counter that rises on real
things -- a story played to its ending, a game completed, a pledge signed --
and never spends. For a savings product the container must only fill; the
accumulation IS the lesson.

Thread-scoped like the pledge; the client shelves the running total so My
Journey can show one tin across conversations.
"""

from __future__ import annotations

from typing import Any

#: Where the tin visibly levels up. Celebration, never spending.
MILESTONES: tuple[int, ...] = (10, 25, 50, 100)

#: What each event drops in. Named here so the values are policy, not magic.
COINS_STORY_FINISHED = 2
COINS_GAME_COMPLETED = 2
COINS_GAME_PERFECT = 5
COINS_PLEDGE_SIGNED = 3
COINS_LESSON_TAUGHT = 2

_CAPTION = {
    "en": "+{delta} in the tin!",
    "es": "¡+{delta} en la alcancía!",
    "fr": "+{delta} dans la tirelire !",
}
_MILESTONE = {
    "en": "The tin is getting heavy — {coins} coins!",
    "es": "¡La alcancía ya pesa — {coins} monedas!",
    "fr": "La tirelire devient lourde — {coins} pièces !",
}


def tin_award(state: Any, delta: int, locale: str) -> dict[str, Any]:
    """The state fragment for `delta` coins: the new tin, and its directive.

    Callers spread this into their own update. The directive carries the new
    total and whether a milestone was crossed, so the client can celebrate
    proportionally -- and the caption is already in the reader's language.
    """
    from app.schemas.directives import TinDirective

    if delta <= 0:
        return {}
    coins = int((state.get("tin") or {}).get("coins") or 0)
    new_total = coins + delta
    milestone = any(coins < m <= new_total for m in MILESTONES)
    caption = (_MILESTONE if milestone else _CAPTION).get(
        locale, (_MILESTONE if milestone else _CAPTION)["en"]
    ).format(delta=delta, coins=new_total)
    return {
        "tin": {"coins": new_total},
        "ui_directives": [
            TinDirective(
                coins=new_total, delta=delta, milestone=milestone, caption=caption
            )
        ],
    }
