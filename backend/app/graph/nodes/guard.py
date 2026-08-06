"""The access matrix, applied. Deterministic, no model, no I/O.

One call to `access.allowed_agents`, one write to state, and a short-circuit
when the answer is empty.

## Why this is its own node

It could be three lines inside `hydrate`. It is separate because it is the
boundary the classifier is confined to, and a boundary you can see in the graph
diagram is a boundary somebody notices before they route around it. `classify`
receives `state.allowed_agents` and nothing else -- it never sees the persona,
never sees the band, and therefore cannot reason its way to an agent this node
excluded. The exclusion happens once, here, in Python.

## The refusal is static text, not a generated one

An empty agent list means the caller's combination is not one this product
serves. Asking a model to phrase that would be asking a model to explain an
authorisation decision it was not shown the inputs to, which produces a fluent
guess. It is also the one turn where latency is least excusable: nothing is
being computed.

So the refusal is a constant, per locale, and it says what to do next.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage

from app.graph.access import allowed_agents as compute_allowed_agents, is_denied
from app.graph.state import AspireState

logger = logging.getLogger(__name__)

#: What a refused caller is told, in the three locales the product ships.
#:
#: Deliberately not an apology and deliberately not an explanation of the rule.
#: "Your persona is not permitted this agent" is both meaningless to a reader
#: and a description of the access matrix to anybody probing it. This says the
#: assistant cannot help with this here, and names the route that can.
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

#: The chip offered alongside the refusal, so it is not a dead end. One option
#: rather than several: there is exactly one thing to do next.
_REFUSAL_CHIP: dict[str, str] = {
    "en": "Get help",
    "es": "Obtener ayuda",
    "fr": "Obtenir de l'aide",
}


def refusal_text(locale: str) -> str:
    """The static refusal for a locale, falling back to English.

    Falling back rather than raising: a locale we do not have copy for is a
    configuration gap, and answering in English beats answering with a
    traceback.
    """
    return _REFUSAL.get(locale, _REFUSAL["en"])


def guard(state: AspireState) -> dict[str, Any]:
    """Compute the permitted agents; halt the turn if there are none.

    Returns a plain update rather than a `Command`. Routing lives in
    `main_graph`'s conditional edge, which reads `halt_reason` -- keeping the
    decision here and the movement there means the graph's shape is readable
    from the graph file rather than scattered across the nodes.
    """
    agents = compute_allowed_agents(
        state.get("persona", ""),
        state.get("age_band", ""),
        state.get("account_status", ""),
        user_id=state.get("user_id"),
    )

    if is_denied(agents):
        # INFO, not WARNING. A refused combination is usually a stale token or
        # a persona/band mismatch after a birthday, not an attack -- and a
        # warning that fires on ordinary operation is a warning people mute.
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
