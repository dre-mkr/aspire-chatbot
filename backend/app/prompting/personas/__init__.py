"""One card per persona, shared by every agent that speaks to a reader."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final

_DIR: Final[Path] = Path(__file__).resolve().parent

#: Which card a persona gets.
KNOWN: Final[frozenset[str]] = frozenset({"stella", "orion", "aurora", "nova"})

#: The card used when the persona is missing or unrecognised.
FALLBACK: Final[str] = "aurora"


@lru_cache(maxsize=8)
def persona_card(persona: str | None) -> str:
    """The card for this persona, verbatim from its file."""
    name = (persona or "").strip().lower()
    if name not in KNOWN:
        name = FALLBACK
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
