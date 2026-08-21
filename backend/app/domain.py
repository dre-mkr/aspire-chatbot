"""Vocabulary shared across every feature package: who is speaking, and in what language."""

from __future__ import annotations

from enum import Enum

__all__ = ["Language", "Persona"]


class Language(str, Enum):
    """The locales this product ships copy for."""

    EN = "en"
    ES = "es"
    FR = "fr"


class Persona(str, Enum):
    """The five assistants a reader can be talking to.

    `GUEST` is the general-purpose one: the reader has told us nothing about
    themselves, so it is written for a mixed audience. It is a voice, not a
    privilege -- `access.allowed_agents` resolves it to whatever the reader's own
    band already grants, so choosing it can never widen what they may reach.
    """

    STELLA = "stella"
    ORION = "orion"
    AURORA = "aurora"
    NOVA = "nova"
    GUEST = "guest"


#: Persona names that no longer exist, and what they became.
#:
#: `everyone` was renamed to `guest` on 20 August 2026, because "Guest" is what
#: the reader is called in the picker and "everyone" only ever made sense from
#: inside the code. The rename is complete everywhere we control -- but a session
#: token minted a minute before the deploy still carries the old word, and so
#: might a `users.persona` row.
#:
#: `normalise_persona` is the one place that knows. Delete this map, and the call
#: sites, once no token older than the deploy can still be in play.
#:
#: The key is the OLD name. It briefly read `{"guest": "guest"}` -- a rename
#: applied twice, once by the branch and once by the patch -- which is a seam
#: that maps nothing and looks like it works.
_RENAMED: dict[str, str] = {"everyone": "guest"}


def normalise_persona(value: str | None) -> str:
    """A persona name from outside this process, under its current name.

    Outside means: a session token, a database row, a query string. Anything
    minted before a rename comes back through here.
    """
    name = (value or "").strip().lower()
    return _RENAMED.get(name, name)
