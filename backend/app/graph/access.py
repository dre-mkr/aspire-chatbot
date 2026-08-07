"""Who is allowed to answer, decided before anything is generated.

A pure function over four values. No model call, no database read, no clock, no
environment. That is the entire design, and every property this module needs
falls out of it: it is testable exhaustively (there are 4 x 5 x 4 x 2 = 160
combinations and the test suite walks all of them), it cannot fail open because
a network call timed out, and it cannot be talked out of its answer by anything
a user types.

The matrix it encodes is a safety control rather than a feature flag. `stella`
is the mascot a six-year-old talks to; the reason she cannot reach
`register_agent` is not that registration would be unhelpful, it is that a
registration flow collects a national ID and a date of birth, and a child must
never be the one supplying them. Likewise `orion` under 16 gets
`qa_agent_limited` -- the same Q&A subgraph with a knowledge-base filter, not a
different, weaker agent (see `agents/qa/graph.py`).

## Registration is a guardian's job, and only a guardian's

`register_agent` appears in exactly one row: `_AURORA`. It used to appear in
three, and each of the two that were removed was defensible on its own and
wrong together with the other one:

  * `_ORION_16_18` let a sixteen-year-old register themselves. A sixteen-year-old
    is old enough to hold an account and is still not the person who should be
    typing a national ID into a chat window to open one.
  * `_NOVA` let staff register somebody at a branch. Acting on another person's
    behalf is a portal function with its own auth realm and its own audit trail
    -- the same argument that already keeps `servicing_agent` off this row.

`register_agent_step1` stays on `_ANONYMOUS`, and the distinction is the point:
step 1 collects what can be collected before an account exists and nothing that
is PII about a minor. A signed-out visitor starting an application is usually a
parent who has not signed in yet, and removing it would close the only route
from the public site into the programme.

## `stella` is a child's persona, so it is bounded by a child's bands

The specification listed `stella` as unrestricted by age band, which meant an
`adult` token that selected the children's mascot dropped into the child lesson
flow. That was read as conservative -- the children's agent set is the narrow
one -- but it is the wrong kind of conservative: the lesson machine writes
mastery rows, picks content off a 5-8 ladder, and is gated by `safety_out` to a
thirty-five word cap. None of that is a sensible thing to hand an adult, and an
adult who wants it can switch persona. `_STELLA_BANDS` is the whole change.

## Anonymous overrides persona

An unauthenticated caller gets the anonymous row whatever persona the client
claims, because persona is chosen in the UI and identity is not. The anonymous
row is deliberately the narrowest one in the table: public Q&A, a taste of the
learning content, the first step of registration, and a route to a human.

## The caller's obligation

An empty list is a hard 403 and every caller must treat it as one. It is
returned for two different situations that are not worth distinguishing here:
a combination the matrix does not cover (`orion` in the 5-8 band -- Orion is the
teen mascot and a six-year-old holding an Orion token is a token to
investigate), and a value outside the closed vocabularies (`persona="root"`).
Both mean the same thing to a caller: serve nothing.

## Known open question

`aurora` and `nova` are unrestricted by age band because the specification's
table lists them that way. In practice a guardian's token carries the `adult`
band, so the permissive rows are unreachable in normal operation. If the
programme ever wants "a guardian token in a child band is itself suspicious"
to be enforced here rather than at token minting, this is the file, and
`test_access.py` will need the corresponding rows.
"""

from __future__ import annotations

from typing import Final

# ── the closed sets ──────────────────────────────────────────────────────────
#
# Deliberately duplicated as runtime frozensets rather than derived from the
# `Literal` types in `state.py`. `typing.get_args` would work, and would also
# mean a type annotation silently becoming the authority for an authorisation
# decision. These are checked at runtime because the values arrive at runtime,
# from a token, and a token is data.

PERSONAS: Final[frozenset[str]] = frozenset({"stella", "orion", "aurora", "nova"})
AGE_BANDS: Final[frozenset[str]] = frozenset({"5-8", "9-12", "13-15", "16-18", "adult"})
ACCOUNT_STATUSES: Final[frozenset[str]] = frozenset(
    {"prospect", "applicant", "beneficiary", "guardian"}
)

#: Every agent name this matrix is allowed to hand out.
#:
#: The router validates against this and the tests assert that no combination
#: ever produces a name outside it. That is the property that stops a typo in a
#: row below -- `"servicing_agnet"` -- from becoming a silent permanent denial
#: that nobody notices because the agent simply never runs.
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

# ── the rows ─────────────────────────────────────────────────────────────────
#
# Written out as literal tuples rather than composed from a base list with
# additions. Composition reads better and makes it materially harder to answer
# the question this file exists to answer -- "can a fourteen-year-old reach
# registration?" -- by looking. Every row states its whole contents.

#: Two agents: learn, and a route to a human.
_STELLA: Final[tuple[str, ...]] = ("learn_agent", "escalate_agent")

#: The bands `stella` covers. A token outside them gets the hard refusal, on the
#: same reasoning as an Orion token in the 5-8 band: the persona and the band
#: disagree, and this is not the place to decide which one is lying.
_STELLA_BANDS: Final[frozenset[str]] = frozenset({"5-8", "9-12"})

#: 13-15. Q&A is the band-filtered variant; registration is absent by design.
_ORION_13_15: Final[tuple[str, ...]] = (
    "learn_agent",
    "qa_agent_limited",
    "escalate_agent",
)

#: 16-18. Old enough to hold and service an account, not the person who opens
#: it -- see the module docstring on why `register_agent` is not here.
_ORION_16_18: Final[tuple[str, ...]] = (
    "learn_agent",
    "qa_agent",
    "servicing_agent",
    "escalate_agent",
)

#: The guardian persona, and the ONLY row that reaches registration.
#:
#: `learning_preview` lets a parent see what their child is being taught. It is
#: the same lesson machine the child runs -- real teaching, real widgets, real
#: check questions -- and it scores nobody: `graph._learner` returns None for
#: it, so nothing a guardian does while looking in is written to a mastery row.
#: That last part was not true until it was measured; see `NON_SCORING_AGENTS`.
_AURORA: Final[tuple[str, ...]] = (
    "qa_agent",
    "register_agent",
    "servicing_agent",
    "escalate_agent",
    "learning_preview",
)

#: Staff and partners. No servicing and no registration: both are acting on
#: somebody else's account, which is a portal function with its own auth realm.
_NOVA: Final[tuple[str, ...]] = ("qa_agent", "escalate_agent")

#: No proven identity. `register_agent_step1` collects only what can be
#: collected before an account exists, and nothing that would be PII about a
#: minor.
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
    """The agents this caller may be routed to. Empty means refuse the turn.

    `user_id` is keyword-only and has no default, and both of those are
    deliberate. The specification gives this function three positional
    arguments and describes an anonymous row keyed on `user_id is None`, which
    cannot both be true -- so the three positional arguments are exactly as
    specified and identity arrives as a fourth argument that no caller can omit.

    A default would have to be one of two wrong things: `None`, making every
    call that forgot the argument silently anonymous (narrow, but wrong), or a
    placeholder, making every such call silently authenticated (wide, and
    dangerous). Requiring it means the question "is this caller signed in?" is
    answered at every call site, which is where it should be answered.

    Returns a fresh list on every call. The rows are module-level tuples and a
    caller that mutated a shared list would be editing the access matrix for
    the rest of the process.
    """
    # Anonymous first, and unconditionally. An unauthenticated caller's persona
    # is a UI preference; it selects a voice and a tone and it does not select
    # a permission. Note this deliberately does NOT validate persona or band:
    # an anonymous caller has no verified claims to validate, and refusing them
    # for sending a nonsense persona would be refusing the public Q&A to a
    # broken client rather than to an attacker.
    if user_id is None:
        return list(_ANONYMOUS)

    # From here the values came out of a signed token, so anything outside the
    # closed vocabularies is a token that should not exist. Refuse rather than
    # fall through to a default row: there is no safe default row.
    if persona not in PERSONAS:
        return []
    if age_band not in AGE_BANDS:
        return []
    if account_status not in ACCOUNT_STATUSES:
        return []

    if persona == "stella":
        # Child bands only. An adult holding a Stella token is either a stale
        # token or an adult who picked the children's mascot from the switcher,
        # and neither is a reason to start writing mastery rows against a
        # 5-8 curriculum ladder. Switching persona is one tap.
        if age_band not in _STELLA_BANDS:
            return []
        return list(_STELLA)

    if persona == "orion":
        if age_band == "13-15":
            return list(_ORION_13_15)
        if age_band == "16-18":
            return list(_ORION_16_18)
        # 5-8, 9-12 and adult are not Orion's bands. A token claiming one is
        # either stale or forged, and either way this is not the place to
        # decide which -- it is the place to serve nothing.
        return []

    if persona == "aurora":
        return list(_AURORA)

    # `nova`, by elimination: the persona set has four members and the three
    # above are handled. Written as the fall-through rather than as a fourth
    # `if` so that adding a fifth persona to `PERSONAS` without adding a row
    # here is caught by the test that walks every persona, instead of quietly
    # inheriting Nova's permissions.
    return list(_NOVA)


def is_denied(agents: list[str]) -> bool:
    """Whether this result is the hard refusal.

    A named predicate rather than `if not agents` at each call site, because
    "empty list" and "hard 403" are the same fact stated at two different
    levels, and the call sites should be reading the second one.
    """
    return not agents
