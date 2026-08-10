"""The access matrix, applied."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage

from app.graph.access import allowed_agents as compute_allowed_agents, is_denied
from app.graph.state import AspireState

logger = logging.getLogger(__name__)

#: What a refused caller is told, in the three locales the product ships.
_REFUSAL: dict[str, str] = {
    "en": (
        "I can't help with that from here. If you need to reach someone at "
        "ASPIRE, tap Get help and a person will pick it up."
    ),
    "es": (
        "No puedo ayudarte con eso desde aquí. Si necesitas hablar con alguien "
        "de ASPIRE, toca Obtener ayuda y una persona te atenderá."
    ),
    "fr": (
        "Je ne peux pas t'aider avec cela ici. Si tu dois joindre quelqu'un "
        "d'ASPIRE, appuie sur Obtenir de l'aide et une personne prendra le relais."
    ),
}

#: The chip offered alongside the refusal, so it is not a dead end.
_REFUSAL_CHIP: dict[str, str] = {
    "en": "Get help",
    "es": "Obtener ayuda",
    "fr": "Obtenir de l'aide",
}


def refusal_text(locale: str) -> str:
    """The static refusal for a locale, falling back to English."""
    return _REFUSAL.get(locale, _REFUSAL["en"])


def guard(state: AspireState) -> dict[str, Any]:
    """Compute the permitted agents; halt the turn if there are none."""
    agents = compute_allowed_agents(
        state.get("persona", ""),
        state.get("age_band", ""),
        state.get("account_status", ""),
        user_id=state.get("user_id"),
    )

    if is_denied(agents):
        # INFO, not WARNING.
        logger.info(
            "No agents for session %s (persona=%s band=%s status=%s anon=%s); "
            "refusing the turn.",
            state.get("session_id"),
            state.get("persona"),
            state.get("age_band"),
            state.get("account_status"),
            state.get("user_id") is None,
        )
        locale = state.get("locale", "en")
        return {
            "allowed_agents": [],
            "halt_reason": "access_denied",
            "messages": [AIMessage(content=refusal_text(locale))],
            "quick_replies": [_REFUSAL_CHIP.get(locale, _REFUSAL_CHIP["en"])],
            "active_agent": None,
        }

    return {"allowed_agents": agents}
