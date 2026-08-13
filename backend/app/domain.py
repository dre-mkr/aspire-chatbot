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
    """The four assistants a reader can be talking to."""

    STELLA = "stella"
    ORION = "orion"
    AURORA = "aurora"
    NOVA = "nova"
