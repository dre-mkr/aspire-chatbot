"""One card per persona, shared by every agent that speaks to a reader."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final

_DIR: Final[Path] = Path(__file__).resolve().parent

#: Which card a persona gets.
KNOWN: Final[frozenset[str]] = frozenset(
    {"stella", "orion", "aurora", "nova", "everyone"}
)

#: The card used when the persona is missing or unrecognised.
#:
#: The most restrictive one. It was `aurora`, so an unknown persona -- a typo in
#: a URL, a value from an older client, a token minted before a rename -- lost
#: every piece of child-safety wording at once and was answered as a guardian.
#: The whole point of a fallback is that it is reached when something has
#: already gone wrong, which is the worst moment to widen what may be said.
FALLBACK: Final[str] = "stella"


@lru_cache(maxsize=8)
def persona_card(persona: str | None) -> str:
    """The card for this persona, verbatim from its file."""
    name = (persona or "").strip().lower()
    if name not in KNOWN:
        name = FALLBACK
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
