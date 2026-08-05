"""Deriving a session's claims from an account record.

The first test in this file exists because of a live lockout, and it is the one
worth reading.

`DEFAULT_PERSONA` mapped the 9-12 band to `orion`. The access matrix grants
Orion only at 13-15 and 16-18, so `allowed_agents("orion", "9-12", …)` returns
`[]` — which every caller must treat as a hard 403. The result: every
nine-to-twelve-year-old was issued a token the matrix denied outright, `guard`
halted the turn, and the whole band was locked out of the product.

Both halves were individually correct. The matrix said what it meant, and the
token was minted exactly as configured. Nothing connected them until a turn was
actually run for that band.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from app.graph import account  # noqa: E402
from app.graph.access import ACCOUNT_STATUSES, allowed_agents  # noqa: E402


# ── the lockout ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("band", sorted(account.DEFAULT_PERSONA))
@pytest.mark.parametrize("status", sorted(ACCOUNT_STATUSES))
def test_every_default_persona_can_actually_reach_an_agent(band: str, status: str):
    """A minted identity must never be one the matrix denies.

    `allowed_agents` returning `[]` is a hard 403 by contract, so a default that
    produces one is not a misconfiguration the product degrades through — it is
    a band that cannot use the product at all.
    """
    persona = account.DEFAULT_PERSONA[band]
    granted = allowed_agents(persona, band, status, user_id="derivation")

    assert granted, (
        f"{persona!r} at {band!r} with {status!r} is granted no agents, so a "
        f"session minted for this band is refused by `guard` on its first turn"
    )


# ── the menu must not offer what the matrix refuses ──────────────────────────

_PERSONAS_TS = (
    Path(__file__).resolve().parents[3] / "frontend/src/lib/aspire/personas.ts"
)

#: `id: "x", name: "…", audience: "…"` from the PERSONAS literal.
_ENTRY = re.compile(
    r'id:\s*"(?P<id>\w+)",\s*name:\s*"[^"]*",\s*audience:\s*"(?P<audience>[^"]*)"'
)
#: "Ages 5–12" -- en dash in the file, hyphen allowed so a reformat is not a
#: false failure.
_AGES = re.compile(r"Ages\s+(\d+)\s*[–-]\s*(\d+)")


def _advertised() -> list[tuple[str, int, int]]:
    text = _PERSONAS_TS.read_text(encoding="utf-8")
    found = []
    for match in _ENTRY.finditer(text):
        ages = _AGES.search(match.group("audience"))
        if ages:  # "Parents & guardians" and "Teachers & educators" carry no ages
            found.append((match.group("id"), int(ages.group(1)), int(ages.group(2))))
    return found


@pytest.mark.skipif(
    not _PERSONAS_TS.exists(), reason="no frontend checkout beside this one"
)
def test_the_persona_menu_never_advertises_an_age_the_matrix_denies():
    """The client's age ranges must be reachable identities (P15-017).

    This is the pin on the mismatch that cost the 9-12 band the whole product.
    `personas.ts` said Orion was for "Ages 10–18"; the matrix grants Orion at
    13-15 and 16-18 only. `DEFAULT_PERSONA` was built from the copy rather than
    the matrix, so every ten-to-twelve-year-old got a token `guard` refused.

    Read out of the real file rather than restated here, because a copy of the
    copy would agree with itself while the product disagreed. One direction only:
    everything ADVERTISED must be granted. The converse is deliberately not
    asserted -- Stella is granted the `adult` band too, and no menu should say so.
    """
    advertised = _advertised()
    assert advertised, f"parsed no age ranges out of {_PERSONAS_TS}"

    today = date(2026, 8, 5)
    offences = []
    for persona, low, high in advertised:
        for age in range(low, high + 1):
            # A birthday on 1 January has always passed by August, so the
            # arithmetic in `band_for` yields exactly `age`.
            band = account.band_for(
                date(today.year - age, 1, 1), is_minor=True, today=today
            )
            if not allowed_agents(persona, band, "beneficiary", user_id="derivation"):
                offences.append((persona, age, band))

    assert not offences, "the persona menu offers what the matrix refuses:\n" + "\n".join(
        f"  {persona!r} advertised at age {age} → band {band!r}, granted no agents"
        for persona, age, band in offences
    )


# ── the band ladder ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("born", "expected"),
    [
        (date(2020, 6, 1), "5-8"),
        (date(2018, 6, 1), "5-8"),
        (date(2017, 6, 1), "9-12"),
        (date(2016, 6, 1), "9-12"),
        (date(2013, 6, 1), "13-15"),
        (date(2010, 6, 1), "16-18"),
        (date(2007, 6, 1), "adult"),
    ],
)
def test_a_date_of_birth_lands_in_the_right_band(born: date, expected: str):
    assert account.band_for(born, is_minor=True, today=date(2026, 8, 5)) == expected


def test_a_birthday_not_yet_reached_this_year_does_not_count():
    """Off-by-one on a birthday moves a child a whole band."""
    born = date(2014, 12, 25)
    today = date(2026, 8, 5)  # 11, turns 12 in December
    assert account.band_for(born, is_minor=True, today=today) == "9-12"


def test_a_minor_with_no_date_of_birth_gets_the_youngest_band():
    """Not knowing an age means treating them as the youngest.

    A record that lost its date of birth is not a reason to grant more. A
    fourteen-year-old briefly offered the five-year-old's mascot is correctable
    by filling the field in; the reverse is not.
    """
    assert account.band_for(None, is_minor=True) == account.YOUNGEST_BAND


def test_an_adult_with_no_date_of_birth_stays_an_adult():
    assert account.band_for(None, is_minor=False) == "adult"


# ── the persona request ──────────────────────────────────────────────────────


def test_a_narrower_persona_is_granted():
    """An adult may prefer Nova's plainer register to Aurora's.

    Nova has no `servicing_agent`, so it is strictly narrower and the request
    costs nothing to honour.
    """
    claims = account.derive(
        born=date(1990, 1, 1),
        is_minor=False,
        account_status="guardian",
        requested_persona="nova",
    )

    assert claims.persona == "nova"
    assert not claims.persona_request_refused


def test_a_wider_persona_is_refused_and_recorded():
    """A six-year-old asking for the guardian persona gets Stella.

    Recorded rather than silently ignored: a client repeatedly asking to widen
    is either a bug or a probe, and neither is visible without the flag.
    """
    claims = account.derive(
        born=date(2020, 1, 1),
        is_minor=True,
        account_status="prospect",
        requested_persona="aurora",
    )

    assert claims.persona == "stella"
    assert claims.persona_request_refused


def test_a_persona_that_grants_nothing_is_refused():
    """Narrower must still mean reachable.

    `orion` at 5-8 is granted no agents at all. It is not "narrower than
    Stella" — it is an identity that cannot hold a conversation, and honouring
    the request would lock the caller out.
    """
    claims = account.derive(
        born=date(2020, 1, 1),
        is_minor=True,
        account_status="prospect",
        requested_persona="orion",
    )

    assert claims.persona == "stella"
    assert claims.persona_request_refused


def test_an_unknown_persona_is_refused():
    claims = account.derive(
        born=date(1990, 1, 1),
        is_minor=False,
        account_status="guardian",
        requested_persona="root",
    )

    assert claims.persona == "aurora"
    assert claims.persona_request_refused
