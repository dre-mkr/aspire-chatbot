"""Who is allowed to answer, decided before anything is generated."""

from __future__ import annotations

from typing import Final

# ── the closed sets ──
# Runtime frozensets, deliberately duplicated from the Literal types in `state`.

PERSONAS: Final[frozenset[str]] = frozenset(
    {"stella", "orion", "aurora", "nova", "guest"}
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
#:
#: `learn_agent` is here to keep `set(_NOVA) <= set(_AURORA)`, which
#: `account._narrowing` reads to decide whether an educator may keep `nova`.
#: Break the subset and `persona_for` silently returns `aurora` for every
#: educator, handing staff the registration walk. It is a real grant too: a
#: guardian who asks how compound interest works should be taught, not quoted a
#: rule.
_AURORA: Final[tuple[str, ...]] = (
    "qa_agent",
    "learn_agent",
    "register_agent",
    "servicing_agent",
    "escalate_agent",
    "learning_preview",
)

#: Staff and partners.
#:
#: Two entries was a bug with a measurable cost. `routable()` drops
#: `escalate_agent`, so this row offered the router exactly ONE candidate and
#: `classify` took its `len(allowed) == 1` shortcut -- no model call, no
#: decision. Measured across the 21 Aug reasoning run: 22 of 22 nova turns were
#: answered by `qa_agent`, including every "how does this work" question, which
#: the fact-lookup agent answers by declining to.
#:
#: `learn_agent` (audience "youth") and `learning_preview` (audience "all") are
#: both narrower than or equal to the `qa_agent` slice this row already held, so
#: neither widens what a staff reader can see -- only who answers them.
_NOVA: Final[tuple[str, ...]] = (
    "qa_agent",
    "learn_agent",
    "learning_preview",
    "escalate_agent",
)

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

    # From a signed token, so anything outside the closed vocabularies is refused.
    if persona not in PERSONAS:
        return []
    if age_band not in AGE_BANDS:
        return []
    if account_status not in ACCOUNT_STATUSES:
        return []

    if persona == "stella":
        # Child bands only.
        if age_band not in _STELLA_BANDS:
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
