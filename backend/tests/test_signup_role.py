"""The role sign-up asks for, and the one combination it must never create."""

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
    """Sign-up must refuse exactly what the derivation would judge non-adult."""
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
