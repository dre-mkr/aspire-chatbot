"""Three unresolved turns on one intent, and only then a person."""

from __future__ import annotations

import re
from typing import Final

from app.agents.escalation.contract import EscalationReason

#: Consecutive unresolved turns on one intent before a person is fetched.
from app.agents.escalate.graph import CLARIFICATION_LIMIT as LIMIT  # noqa: E402

__all__ = ["LIMIT", "intent_key", "bump", "clear", "at_limit", "escalation_for"]

_WORD = re.compile(r"[a-z0-9']+")

#: Words that carry no topic.
_STOP: Final[frozenset[str]] = frozenset(
    """
    a an the is are was were do does did can could would should will shall may
    might i you he she it we they me my your our their this that these those
    to of for from with about on in at by and or but if so what which who whom
    whose when where why how please tell me know want need get give show
    """.split()
)


def intent_key(text: str, *, keep: int = 6) -> str:
    """A stable, coarse key for "the same thing, asked again"."""
    words = [word for word in _WORD.findall((text or "").lower()) if word not in _STOP]
    return " ".join(sorted(words)[:keep])


def bump(streaks: dict[str, int] | None, text: str) -> dict[str, int]:
    """The streak after one more unresolved turn."""
    key = intent_key(text)
    if not key:
        # Nothing to key on ("?", an emoji).
        return {}
    current = (streaks or {}).get(key, 0)
    return {key: current + 1}


def clear(streaks: dict[str, int] | None = None) -> dict[str, int]:
    """The streak after a resolved turn."""
    return {}


def at_limit(streaks: dict[str, int] | None, text: str) -> bool:
    """Whether this intent has now failed `LIMIT` times in a row."""
    return (streaks or {}).get(intent_key(text), 0) >= LIMIT


def escalation_for(streaks: dict[str, int] | None, text: str) -> EscalationReason | None:
    """`REPEATED_FAILURE` if the streak has run out, else None."""
    return EscalationReason.REPEATED_FAILURE if at_limit(streaks, text) else None
