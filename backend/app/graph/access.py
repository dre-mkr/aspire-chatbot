"""Who is allowed to answer, decided before anything is generated."""

from __future__ import annotations

from typing import Final

# ── the closed sets ──
# Runtime frozensets, deliberately duplicated from the Literal types in `state`.

PERSONAS: Final[frozenset[str]] = frozenset(
    {"stella", "kaleb", "orion", "aurora", "nova", "guest"}
)
AGE_BANDS: Final[frozenset[str]] = frozenset({"5-8", "9-12", "13-15", "16-18", "adult"})
ACCOUNT_STATUSES: Final[frozenset[str]] = frozenset(
    {"prospect", "applicant", "beneficiary", "guardian"}
)

#: Every agent name this matrix is allowed to hand out.
KNOWN_AGENTS: Final[frozenset[str]] = frozenset(
    {
        "learn_agent",
        "learning_preview",
        "learning_sample",
        "qa_agent",
        "qa_agent_limited",
        "qa_agent_public",
        "register_agent",
        "register_agent_step1",
        "servicing_agent",
        "escalate_agent",
    }
)

# ── the rows ──
# Written out as literal tuples rather than computed, so every row can be read on its own.

#: Q&A first: it is the default agent for every reader, and row order is what makes it the fallback.
_STELLA: Final[tuple[str, ...]] = ("qa_agent_limited", "learn_agent", "escalate_agent")

#: The bands `stella` covers.
_STELLA_BANDS: Final[frozenset[str]] = frozenset({"5-8", "9-12"})

#: 13-15. Q&A first (the default agent); the band-filtered variant.
_ORION_13_15: Final[tuple[str, ...]] = (
    "qa_agent_limited",
    "learn_agent",
    "escalate_agent",
)

#: 16-18.
_ORION_16_18: Final[tuple[str, ...]] = (
    "qa_agent",
    "learn_agent",
    "servicing_agent",
    "escalate_agent",
)

#: The guardian persona, and the ONLY row that reaches registration.
_AURORA: Final[tuple[str, ...]] = (
    "qa_agent",
    "register_agent",
    "servicing_agent",
    "escalate_agent",
    "learning_preview",
)

#: Staff and partners.
_NOVA: Final[tuple[str, ...]] = ("qa_agent", "escalate_agent")

#: No proven identity.
_ANONYMOUS: Final[tuple[str, ...]] = (
    "qa_agent_public",
    "learning_sample",
    "register_agent_step1",
    "escalate_agent",
)


def allowed_agents(
    persona: str,
    age_band: str,
    account_status: str,
    *,
    user_id: str | None,
) -> list[str]:
    """The agents this caller may be routed to."""
    # Anonymous first, and unconditionally.
    if user_id is None:
        return list(_ANONYMOUS)

    # An old token says `stella` where this now says `kaleb`. Applied before the
    # vocabulary check, so the pair that moved is answered under its new name
    # rather than falling through to the empty list.
    from app.domain import normalise_persona_band

    persona = normalise_persona_band(persona, age_band)

    # From a signed token, so anything outside the closed vocabularies is refused.
    if persona not in PERSONAS:
        return []
    if age_band not in AGE_BANDS:
        return []
    if account_status not in ACCOUNT_STATUSES:
        return []

    if persona == "stella":
        # Skye alone now: `kaleb.9-12.md` took the older band with it.
        if age_band != "5-8":
            return []
        return list(_STELLA)

    if persona == "kaleb":
        # THE SAME SET STELLA GRANTED AT 9-12, deliberately unchanged. Kaleb
        # becoming a key of his own is a change of vocabulary, not of
        # entitlement: he is the same child reader, at the same band, reaching
        # the same agents. Anything wider would make a naming fix into a
        # privilege change, which is not what it was asked to be.
        if age_band != "9-12":
            return []
        return list(_STELLA)

    if persona == "orion":
        if age_band == "13-15":
            return list(_ORION_13_15)
        if age_band == "16-18":
            return list(_ORION_16_18)
        # 5-8, 9-12 and adult are not Orion's bands.
        return []

    if persona == "aurora":
        return list(_AURORA)

    if persona == "guest":
        # The general-purpose voice, and deliberately NOT a row of its own.
        #
        # `guest` says "I have not told you who I am", which is a statement
        # about register, not about entitlement. Giving it a literal row would
        # mean inventing a set that is either wider than the reader's own --- a
        # privilege escalation available to anyone who edits a URL --- or
        # narrower, which would silently take registration away from a guardian
        # who picked it to read something in plainer words.
        #
        # So it resolves to the safe default for the band the token already
        # carries. Every result below is a set some other persona already grants
        # at that band, which is what makes `_narrowing` admit this persona from
        # any account: it never returns anything the caller did not already have.
        if age_band in _STELLA_BANDS:
            return list(_STELLA)
        if age_band == "13-15":
            return list(_ORION_13_15)
        if age_band == "16-18":
            return list(_ORION_16_18)
        # `adult`: factual answers and a way to reach a person. Registration is
        # Aurora's alone and stays there.
        return list(_NOVA)

    # `nova`, by elimination: the persona set's other four members are handled above.
    return list(_NOVA)


def is_denied(agents: list[str]) -> bool:
    """Whether this result is the hard refusal."""
    return not agents
