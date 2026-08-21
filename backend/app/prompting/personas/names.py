"""The display label for each persona, which is not the persona's key.

Rename the label. Never rename the key.

`"stella"` appears about fifty times across this codebase -- `DEFAULT_PERSONA`,
`_ANONYMOUS_BANDS`, `ROLE_PERSONA`, the access matrix, the session token, the
tests, and whatever the front end sends. It is a database id that happens to be
a word, so renaming it is a migration; renaming it on the day a client picks a
nicer name is a migration nobody planned.

So the two are separated permanently. Cards say `{name}` and the label lives
here. A rename is one line and a test run, and it leaves room for a persona to
carry a different name in Spanish or French later, if that is ever wanted.
"""

from __future__ import annotations

from typing import Final

NAMES: Final[dict[str, str]] = {
    "stella": "Skye",  # <- change this line, and only this line
    "orion": "Zion",
    "aurora": "Imani",
    "nova": "Azuri",
    "everyone": "Guest",
}

#: Labels that belong to one band rather than to the whole persona.
#:
#: `stella` is one persona key and two voices. The 5-8 card is a gentle,
#: wondering helper for a child who cannot yet read a rate; the 9-12 card is a
#: dry older cousin who names the EC$500 split and shows the workings. Giving
#: both the same name was the thing readers noticed first -- a twelve-year-old
#: greeted by the voice written for a six-year-old -- and the two cards have
#: been separate files since. The label follows the card, not the key.
#:
#: Only the pairs that differ appear here. Everything else falls through to
#: `NAMES`, so a persona whose voice does not change with age is still a
#: one-line rename.
BAND_NAMES: Final[dict[tuple[str, str], str]] = {
    ("stella", "9-12"): "Kaleb",
}

#: What a card's `{name}` placeholder is written as.
PLACEHOLDER: Final[str] = "{name}"


def display_name(persona: str | None, age_band: str | None = None) -> str:
    """The label a reader may be shown, for a persona at an age band.

    The band is optional so that a caller who genuinely does not know it -- the
    picker in the front end, a log line, a test -- still gets the persona's own
    label rather than an error. A caller that HAS the band gets the band's
    label, which is the only way `stella` can answer to two names.
    """
    key = (persona or "").strip().lower()
    band = (age_band or "").strip()
    return BAND_NAMES.get((key, band)) or NAMES.get(key, "")


def all_labels() -> frozenset[str]:
    """Every label in use, whole-persona and per-band alike.

    One place for the tests that check no card spells a name out, so adding a
    band label cannot quietly escape the check that a card must not hardcode it.
    """
    return frozenset(NAMES.values()) | frozenset(BAND_NAMES.values())
