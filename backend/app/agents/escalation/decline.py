"""The third outcome: saying we do not know, usefully."""

from __future__ import annotations

from typing import Any

from app.graph.state import AspireState, KBChunk

#: How the decline opens, by band.
_OPENING: dict[str, dict[str, str]] = {
    "en": {
        "5-8": "I do not know that one!",
        "9-12": "I do not have that one.",
        "13-15": "I do not have an answer for that.",
        "16-18": "I do not have an answer for that.",
        "adult": "I do not have an answer for that.",
    },
    "es": {
        "5-8": "¡Esa no me la sé!",
        "9-12": "Esa no la tengo.",
        "13-15": "No tengo una respuesta para eso.",
        "16-18": "No tengo una respuesta para eso.",
        "adult": "No tengo una respuesta para eso.",
    },
    "fr": {
        "5-8": "Celle-là, je ne la sais pas !",
        "9-12": "Je ne l'ai pas.",
        "13-15": "Je n'ai pas de réponse à cela.",
        "16-18": "Je n'ai pas de réponse à cela.",
        "adult": "Je n'ai pas de réponse à cela.",
    },
}

#: Part 2 -- who holds the rest.
_WHO_HOLDS_IT: dict[str, dict[str, str]] = {
    "en": {
        "child": "Ask a grown-up to check with the ASPIRE team.",
        "adult": "The ASPIRE team can answer it — aspire.gov.kn, or any branch.",
    },
    "es": {
        "child": "Pide a una persona mayor que consulte al equipo de ASPIRE.",
        "adult": "El equipo de ASPIRE puede responder — aspire.gov.kn, o una sucursal.",
    },
    "fr": {
        "child": "Demande à un adulte de contacter l'équipe ASPIRE.",
        "adult": "L'équipe ASPIRE peut répondre — aspire.gov.kn, ou une agence.",
    },
}

#: Part 3 -- the offer.
_OFFER: dict[str, str] = {
    "en": 'You could ask me this one instead: "{topic}"',
    "es": 'Puedes preguntarme esto: "{topic}"',
    "fr": 'Tu peux me demander ceci : "{topic}"',
}

_CHILD_BANDS = frozenset({"5-8", "9-12"})


def _band(state: AspireState) -> str:
    return str(state.get("age_band") or "adult")


def _locale(state: AspireState) -> str:
    locale = str(state.get("locale") or "en")
    return locale if locale in _OPENING else "en"


def nearest_topic(chunks: list[KBChunk]) -> str | None:
    """A topic the corpus can actually answer, from the best chunk's own title."""
    for chunk in chunks:
        title = (chunk.title or "").strip()
        if title:
            return title
    return None


def decline_text(state: AspireState, chunks: list[KBChunk]) -> str:
    """The three-part decline, assembled for this reader."""
    locale, band = _locale(state), _band(state)
    audience = "child" if band in _CHILD_BANDS else "adult"

    parts = [
        _OPENING[locale].get(band, _OPENING[locale]["adult"]),
        _WHO_HOLDS_IT[locale][audience],
    ]

    topic = nearest_topic(chunks)
    if topic:
        parts.append(_OFFER[locale].format(topic=topic))

    return " ".join(parts)


def decline_chips(state: AspireState, chunks: list[KBChunk]) -> list[str]:
    """Chips under a decline."""
    topic = nearest_topic(chunks)
    if not topic:
        return []
    words = topic.rstrip("?").split()
    return [" ".join(words[:4])]


def decline_update(state: AspireState, chunks: list[KBChunk]) -> dict[str, Any]:
    """The state update for a declined turn, minus the streak."""
    from langchain_core.messages import AIMessage

    return {
        "messages": [AIMessage(content=decline_text(state, chunks))],
        "quick_replies": decline_chips(state, chunks),
        # A decline cites nothing.
        "citations": [],
        "groundedness": 0.0,
    }
