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
    """The six assistants a reader can be talking to.

    `KALEB` is a key of his own rather than a band of `STELLA`. He was the one
    label carried by `BY_BAND`, which meant the picker offered six guides while
    the vocabulary held five, and every layer below -- access, games, the token,
    the anonymous default -- could only ever see the five. A reader who chose
    Kaleb was a `stella` reader everywhere except the greeting.

    `GUEST` is the general-purpose one: the reader has told us nothing about
    themselves, so it is written for a mixed audience. It is a voice, not a
    privilege -- `access.allowed_agents` resolves it to whatever the reader's own
    band already grants, so choosing it can never widen what they may reach.
    """

    STELLA = "stella"
    KALEB = "kaleb"
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

#: Personas that SPLIT rather than being renamed, keyed by (old persona, band).
#:
#: `stella` carried both child bands until 21 August 2026, when the 9-12 half
#: became `kaleb` with a key and a card of its own. A rename map cannot express
#: this: `stella` still exists and is still correct at 5-8, so the old name maps
#: to the new one ONLY at the band that moved.
#:
#: Without this seam the split is a live outage rather than a deploy. Every
#: session token minted before it carries `stella` with band `9-12`, and
#: `allowed_agents` now answers that pair with an empty list -- every
#: nine-to-twelve-year-old mid-conversation would have lost every agent at once.
#:
#: Delete once no token older than the deploy can still be in play, on the same
#: terms as `_RENAMED`.
_SPLIT: dict[tuple[str, str], str] = {("stella", "9-12"): "kaleb"}


def normalise_persona_band(value: str | None, band: str | None) -> str:
    """A persona name from outside this process, under the name this band uses.

    `normalise_persona` first, so a pre-rename name is current before the split
    map is consulted, and the two seams compose rather than racing.
    """
    name = normalise_persona(value)
    return _SPLIT.get((name, (band or "").strip()), name)


def normalise_persona(value: str | None) -> str:
    """A persona name from outside this process, under its current name.

    Outside means: a session token, a database row, a query string. Anything
    minted before a rename comes back through here.
    """
    name = (value or "").strip().lower()
    return _RENAMED.get(name, name)
