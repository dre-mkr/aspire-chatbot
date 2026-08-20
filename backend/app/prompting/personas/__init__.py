"""One card per persona and age band, shared by every agent that speaks to a reader."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final

from app.graph.state import AGE_BANDS
from app.prompting.personas.names import NAMES, PLACEHOLDER, display_name

_DIR: Final[Path] = Path(__file__).resolve().parent

#: Which card a persona gets.
#:
#: `NAMES` plus `everyone`. `everyone` is a persona everywhere else -- `domain.py`,
#: `access.py`, `state.py` -- but it is the absence of an audience rather than a
#: character, so it has no display name and cannot come from `NAMES` alone.
KNOWN: Final[frozenset[str]] = frozenset(NAMES) | {"everyone"}

#: The card used when the persona is missing or unrecognised.
#:
#: The most restrictive one. It was `aurora`, so an unknown persona -- a typo in
#: a URL, a value from an older client, a token minted before a rename -- lost
#: every piece of child-safety wording at once and was answered as a guardian.
#: The whole point of a fallback is that it is reached when something has
#: already gone wrong, which is the worst moment to widen what may be said.
FALLBACK: Final[str] = "stella"

#: The band a card falls back to when the caller names none.
#:
#: The youngest, for the same reason `FALLBACK` is `stella`: not knowing how old
#: the reader is has to mean the careful card, never the permissive one.
FALLBACK_BAND: Final[str] = "5-8"


def _youngest_card(persona: str) -> Path | None:
    """The most restrictive band card this persona has, if it has any.

    Youngest rather than nearest, because a missing band means the caller does
    not really know who is reading -- and the safe direction to be wrong in is
    the careful card, not the permissive one.
    """
    for band in AGE_BANDS:
        path = _DIR / f"{persona}.{band}.md"
        if path.is_file():
            return path
    return None


@lru_cache(maxsize=64)
def _card_text(persona: str, band: str) -> str:
    """The most specific card on disk for this persona and band.

    `{persona}.{band}.md`, then the persona's undifferentiated `{persona}.md`,
    then its own youngest band card, then the fallback persona. An unknown band
    falls back rather than raising: a reader must never be shown a stack trace
    because somebody added a band and forgot a file.

    `{persona}.md` sits second on purpose. It is the safety net while the band
    split lands, and it keeps a reader with an unrecognised band inside the
    persona they were assigned; once the four undifferentiated cards are
    deleted, the step below it keeps that property.
    """
    candidates = (
        _DIR / f"{persona}.{band}.md",
        _DIR / f"{persona}.md",
        _youngest_card(persona),
        _youngest_card(FALLBACK),
        _DIR / f"{FALLBACK}.md",
    )
    for path in candidates:
        if path is not None and path.is_file():
            return path.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(f"No persona card for {persona!r} at band {band!r}")


def persona_card(persona: str | None, age_band: str | None = None) -> str:
    """The card for this persona at this age band, with the display name filled in.

    The band is optional so that every existing caller keeps working while the
    ones that have a band are moved over one at a time. A caller with no band
    gets the youngest card, which is the safe direction to be wrong in.

    `{name}` is substituted here rather than written into the files, because
    "stella" is an identifier the access matrix, `DEFAULT_PERSONA`,
    `_ANONYMOUS_BANDS` and the session token all depend on, while the label a
    reader sees is a client's choice. Separating them makes a rename one line in
    `names.py` instead of a migration.
    """
    name = (persona or "").strip().lower()
    if name not in KNOWN:
        name = FALLBACK
    band = (age_band or "").strip() or FALLBACK_BAND
    # `str.replace`, not `str.format`: a card is prose that may one day contain a
    # brace, and `format` would raise on it in front of a reader.
    return _card_text(name, band).replace(PLACEHOLDER, display_name(name))
