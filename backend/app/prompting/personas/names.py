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
    "stella": "Sky",  # <- change this line, and only this line
    "orion": "Prosper",
    "aurora": "Destiny",
    "nova": "Star",
}

#: What a card's `{name}` placeholder is written as.
PLACEHOLDER: Final[str] = "{name}"


def display_name(persona: str | None) -> str:
    """The label a reader may be shown, for a persona key."""
    return NAMES.get((persona or "").strip().lower(), "")
