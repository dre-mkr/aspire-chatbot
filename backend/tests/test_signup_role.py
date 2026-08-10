"""The role sign-up asks for, and the one combination it must never create.

## The account that could not be repaired

Sign-up used to collect one date of birth in the second person and derive
everything after it, including the persona. That has exactly one correct
reading -- a participant entering their own date -- and the form never said so.
A parent filling it in for a child entered the child's date, which is the
obvious reading of a page headed "Let us start with you" when the reason you
are on it is your daughter.

The account then landed in a child band, and `register_agent` is granted to
`aurora` alone. Aurora is WIDER than a teen band's persona, so `_narrowing`
refuses a request to switch:

    WARNING app.api.stream: Refused a request for persona 'aurora'
    on a 16-18 band session.

Nothing in the product could fix that account. Not the picker, not the
assistant, not a settings page -- only registering a second one.

So the combination is refused at the single moment it is cheap to correct, and
these tests are the pin on that. The alternative considered and rejected was to
let a self-declared role override the band, which hands a flow that collects a
national ID to anybody who ticks a box.

## Why these are fast

`_role_problem` is pure. The endpoint tests around it in
`test_accounts_claim.py` need Postgres and bcrypt and take minutes; this is the
rule itself, and the rule is what has to be right.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from app.accounts import ADULT_ROLES, ROLES, _role_problem  # noqa: E402
from app.graph.account import band_for  # noqa: E402

#: Comfortably an adult under `band_for`, which is the authority here.
ADULT = date(1990, 6, 1)


@pytest.mark.parametrize("role", sorted(ROLES))
def test_an_adult_date_of_birth_is_accepted_for_every_role(role: str) -> None:
    assert _role_problem(role, ADULT) is None


@pytest.mark.parametrize("role", sorted(ADULT_ROLES))
@pytest.mark.parametrize(
    "born",
    [
        date(2018, 6, 1),  # 5-8
        date(2015, 6, 1),  # 9-12
        date(2012, 6, 1),  # 13-15
        date(2009, 6, 1),  # 16-18
    ],
)
def test_an_adult_role_is_refused_a_child_date_of_birth(role: str, born: date) -> None:
    """The trap, closed. Each of these is an account nothing could repair."""
    problem = _role_problem(role, born)

    assert problem is not None
    assert problem.strip()


def test_a_participant_may_be_any_age() -> None:
    """ASPIRE is a programme for children. The common case must stay unblocked."""
    for born in (date(2020, 6, 1), date(2015, 6, 1), date(2009, 6, 1), ADULT):
        assert _role_problem("participant", born) is None


def test_an_unknown_role_is_refused_rather_than_defaulted() -> None:
    """Silently treating it as `participant` would make a client typo look fine."""
    assert _role_problem("administrator", ADULT) is not None
    assert _role_problem("", ADULT) is not None


@pytest.mark.parametrize("role", sorted(ADULT_ROLES))
def test_the_refusal_boundary_is_the_band_table_and_not_a_local_constant(
    role: str,
) -> None:
    """Sign-up must refuse exactly what the derivation would judge non-adult.

    A separate `ADULT_AGE = 18` here would have been off by one against
    `band_for`, which puts an eighteen-year-old in `16-18` -- so sign-up would
    have accepted an account the persona derivation then refused to give the
    guardian persona to. That is this whole bug, rebuilt one layer up.

    Walked over a range of ages rather than asserted at a threshold, so the two
    cannot drift apart silently.

    The real current date, not a fixed one: `_role_problem` calls `band_for`
    without a `today`, so a pinned date here would agree with it until the year
    rolled over and then fail for a reason that has nothing to do with the rule.
    """
    today = date.today()
    for age in range(5, 40):
        born = date(today.year - age, 1, 1)
        accepted = _role_problem(role, born) is None
        adult_band = band_for(born, is_minor=False, today=today) == "adult"
        assert accepted == adult_band, (
            f"age {age}: sign-up {'accepts' if accepted else 'refuses'} a "
            f"{role!r} whose band is "
            f"{band_for(born, is_minor=False, today=today)!r}"
        )
