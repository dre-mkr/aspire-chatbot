"""Who is allowed to answer, decided before anything is generated."""

from __future__ import annotations

import logging
from typing import Final

logger = logging.getLogger(__name__)

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

#: What an adult who has NOT said who they are may reach.
#:
#: Factual answers and a way to reach a person. Registration is Aurora's alone
#: and stays there; teaching belongs to a reader whose band is known.
#:
#: THIS USED TO BE `_NOVA` ITSELF, and the reuse was invisible until Azuri's row
#: was widened: `guest` at `adult` returned `list(_NOVA)`, so giving the teacher
#: persona a tutor silently gave one to every unidentified adult as well, and
#: `TestEveryoneNeverWidens` caught it -- guest granting something the persona
#: it stands in for does not is precisely the escalation that test exists to
#: stop. Two rows that happened to be equal are now two rows.
_ADULT_MINIMUM: Final[tuple[str, ...]] = ("qa_agent", "escalate_agent")


#: Teachers and educators.
#:
#: Was `("qa_agent", "escalate_agent")` under the label "Staff and partners" --
#: two agents, the most restricted signed-in row in the system: answer a
#: question, or fetch a human. THE TEACHER PERSONA WAS THE ONE THAT COULD
#: NEITHER TEACH NOR BE TAUGHT, while `aurora` -- a parent -- held
#: `learning_preview` and could see the lessons Azuri delivers.
#:
#: `learning_preview` is the adult-facing view of what a child is taught. A
#: teacher has a stronger claim on it than a guardian does: the guardian is
#: curious about it, the teacher is delivering it. Withholding it meant Azuri
#: could describe ASPIRE's teaching and never show any.
#:
#: NOT `learn_agent`, and the reason is a constraint rather than a judgement.
#:
#: `_narrowing` lets an adult PICK a plainer persona only when that persona's
#: row is a subset of their own, which is what stops picking one being a way to
#: reach more. `aurora` has no `learn_agent`. Give one to `nova` and the subset
#: breaks: a guardian can no longer choose Azuri's register, and an educator
#: ROLE stops resolving to Azuri at all. Both were live test failures, and both
#: are real behaviour, not bookkeeping.
#:
#: Fixing that properly means giving the tutor to `aurora` as well -- which may
#: well be right, since a parent learning what compounding is sits squarely in
#: what ASPIRE is for. It is a decision about the GUARDIAN persona, taken on
#: purpose rather than as a side effect of widening the teacher's, and it is not
#: this change.
#:
#: STILL NOT REGISTRATION OR SERVICING. A teacher enrolling children on their
#: behalf, or reading an account that is not theirs, is a safeguarding question
#: with an owner, and that owner is not this file.
_NOVA: Final[tuple[str, ...]] = (
    "qa_agent",
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


def _refused(persona: str, age_band: str) -> list[str]:
    """Zero agents for a persona and band that are each individually valid.

    THIS IS THE FAILURE MODE THAT DOES NOT ANNOUNCE ITSELF. Both values passed
    the closed-vocabulary checks above, so nothing is malformed and nothing
    raises -- the caller simply gets an empty list and the reader gets an
    assistant that cannot answer anything. No stack trace, no 500, no alert.

    The way it happens in practice is a persona whose bands changed while
    tokens minted under the old shape are still valid. `stella` losing 9-12 to
    `kaleb` is exactly that, `TOKEN_TTL` is seven days, and `_SPLIT` is what
    keeps those tokens working. If `_SPLIT` is ever removed early, this line is
    where it will show up -- so it logs at WARNING with both values, rather
    than leaving somebody to infer it from a week of silent, useless sessions.

    A legitimately impossible pair -- `orion` at `5-8` from a hand-edited token
    -- lands here too and is also worth a line.
    """
    logger.warning(
        "No agents for persona %r at band %r: both are valid on their own, so "
        "this is a pair the access matrix has no row for. If it is a band that "
        "recently moved between personas, check the compatibility seam in "
        "`app.domain._SPLIT` before assuming the token is bad.",
        persona,
        age_band,
    )
    return []


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
            return _refused(persona, age_band)
        return list(_STELLA)

    if persona == "kaleb":  # noqa: E501 -- see `_refused` below for why this branch is loud
        # THE SAME SET STELLA GRANTED AT 9-12, deliberately unchanged. Kaleb
        # becoming a key of his own is a change of vocabulary, not of
        # entitlement: he is the same child reader, at the same band, reaching
        # the same agents. Anything wider would make a naming fix into a
        # privilege change, which is not what it was asked to be.
        if age_band != "9-12":
            return _refused(persona, age_band)
        return list(_STELLA)

    if persona == "orion":
        if age_band == "13-15":
            return list(_ORION_13_15)
        if age_band == "16-18":
            return list(_ORION_16_18)
        # 5-8, 9-12 and adult are not Orion's bands.
        return _refused(persona, age_band)

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
        # Aurora's alone and stays there, and so is teaching -- a tutor needs a
        # band, and this reader has not given one.
        return list(_ADULT_MINIMUM)

    # `nova`, by elimination: the persona set's other four members are handled above.
    return list(_NOVA)


def is_denied(agents: list[str]) -> bool:
    """Whether this result is the hard refusal."""
    return not agents
