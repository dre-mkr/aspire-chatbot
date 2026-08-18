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

    `EVERYONE` is the general-purpose one: the reader has told us nothing about
    themselves, so it is written for a mixed audience. It is a voice, not a
    privilege -- `access.allowed_agents` resolves it to whatever the reader's own
    band already grants, so choosing it can never widen what they may reach.
    """

    STELLA = "stella"
    ORION = "orion"
    AURORA = "aurora"
    NOVA = "nova"
    EVERYONE = "everyone"
