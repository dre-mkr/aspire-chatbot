"""Deriving a session's claims from an account record."""

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
    """A minted identity must never be one the matrix denies."""
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

#: The persona and audience of each entry in the GUIDES literal.
#:
#: It read the PERSONAS literal until `audience` was lifted out of it, leaving
#: this regex matching nothing at all -- which the `assert advertised` below
#: caught. GUIDES is where a guide is described now, and `persona` is the key
#: the matrix is asked about. `band` is present on some rows and not others.
_ENTRY = re.compile(
    r'persona:\s*"(?P<id>\w+)",\s*'
    r'(?:band:\s*"[^"]*",\s*)?'
    r'name:\s*"[^"]*",\s*'
    r'audience:\s*"(?P<audience>[^"]*)"'
)
#: "Ages 5–12" -- en dash in the file, hyphen allowed so a reformat is not a false failure.
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
    """The client's age ranges must be reachable identities (P15-017)."""
    advertised = _advertised()
    assert advertised, f"parsed no age ranges out of {_PERSONAS_TS}"

    today = date(2026, 8, 5)
    offences = []
    for persona, low, high in advertised:
        for age in range(low, high + 1):
            # A 1 January birthday has passed by August, so `band_for` yields `age`.
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
    """Not knowing an age means treating them as the youngest."""
    assert account.band_for(None, is_minor=True) == account.YOUNGEST_BAND


def test_no_date_of_birth_is_the_youngest_band_whatever_is_minor_says():
    """
    "We were not told" must not resolve to "adult" on a service for five-year-olds.

    This asserted the opposite, and `is_minor` decided it. But `is_minor` is a
    flag on the row, not a fact about the reader: measured on the shared
    database, 30,327 anonymous rows and 148 REGISTERED participants carry no
    date of birth with `is_minor` false, and every one was banded adult -- no
    word caps, no vocabulary rules, links left in. A participant is eighteen or
    under by definition, so adult was not just the unsafe reading there, it was
    the wrong one.

    Nothing adult-facing regresses: no guardian or educator row has a null date
    of birth, and `_role_problem` takes a required `date`, so signup cannot make
    one.
    """
    assert account.band_for(None, is_minor=False) == account.YOUNGEST_BAND
    assert account.band_for(None, is_minor=True) == account.YOUNGEST_BAND


# ── the signed-out visitor ───────────────────────────────────────────────────
#
# `anonymous_claims` decides what every signed-out visitor is served and had no
# test of any kind. It is the widest audience the service has.


#: Bands that carry the word caps, the vocabulary ladder, the link strip and the
#: minor game set. Anything outside this is the ungated adult row.
MINOR_BANDS = ("5-8", "9-12", "13-15", "16-18")


def test_a_visitor_who_picks_nothing_gets_the_mixed_audience_voice():
    """
    This default has now moved twice, and both moves were for the same reason.

    It was `aurora`, so an anonymous session ran as an adult: no word caps, no
    vocabulary rules, links left in, and the adult game set -- for the one reader
    whose age is genuinely unknown. That was corrected to `stella`.

    But `stella` is the FIVE-TO-EIGHT voice. A signed-out visitor is just as
    likely to be a parent, a teacher, or somebody opening the link cold to judge
    it, and every one of them was being answered as a seven-year-old on their
    first message.

    `everyone` is the voice built for exactly this reader. See the next test for
    why it is not a loosening.
    """
    claims = account.anonymous_claims()

    assert claims.persona == "guest"
    assert claims.account_status == "prospect"


def test_the_mixed_audience_default_is_an_adult():
    """`guest` is the general-public voice, and its reader is an adult.

    This used to resolve to `13-15` on the reasoning that `adult` "would hand an
    unknown reader the ungated row". Measured against the tables, it does not --
    and the next test is that measurement, kept as an assertion so the claim
    cannot rot.

    A child gets a child's band by PICKING a child persona, which is what the
    menu is for. The default is the person the guide is written for.
    """
    claims = account.anonymous_claims()

    assert claims.persona == "guest"
    assert claims.age_band == "adult"
    assert claims.age_band == account._ANONYMOUS_BANDS["guest"]


def test_and_the_only_gate_that_moved_was_length():
    """What `13-15` was actually buying `guest`, gate by gate.

    Four of the five are identical at both bands, so moving the default changed
    one thing: the word cap. The `_NEVER_CLAIM` list holds at every band anyway,
    including `adult`, so nothing a reader must never be told became sayable.
    """
    from app.agents.learn.tools.games import available_for
    from app.graph.access import allowed_agents
    from app.graph.nodes.classify import routable
    from app.graph.nodes.safety_out import cap_for, strips_links
    from app.safety import vocab

    # 1. the vocabulary LADDER -- not one word differs between the two bands
    probe = ["loan", "credit", "interest", "invest", "mortgage", "dividend",
             "risk-free", "guaranteed return"]
    assert [w for w in probe if vocab.check(w, "13-15")] == [
        w for w in probe if vocab.check(w, "adult")
    ], "the ladder is not identical at the two bands after all"

    # 2. links -- already un-stripped for `guest` at 13-15
    assert strips_links("guest", "13-15") == strips_links("guest", "adult") is False

    # 3. games -- the same set
    assert available_for("13-15", "guest") == available_for("adult", "guest")

    # 4. agents -- the same row
    assert routable(allowed_agents("guest", "13-15", "prospect", user_id=None)) == routable(
        allowed_agents("guest", "adult", "prospect", user_id=None)
    )

    # 5. length -- the one that did move, and deliberately
    assert cap_for("13-15", "qa_agent_public") == 280
    assert cap_for("adult", "qa_agent_public") is None


def test_the_default_reader_may_now_have_a_topic_named_to_them():
    """A second consequence, from combining two changes in one release.

    `_NOT_FOR_MINORS` bars `crypto` and `day trading` below `adult`, and the
    signed-out default is now `adult` -- so a visitor whose age is unknown can
    have those topics NAMED. Asserted rather than left to be discovered.

    It is a smaller thing than it reads as. Naming is not advising: the reply
    still declines to recommend, and the alternative was the circumlocution the
    topic ban produced -- "some kinds of online money can lose or gain value
    very quickly" -- which was neither clearer nor safer, just vaguer. A reader
    who wants a child's gating picks a child persona.
    """
    from app.safety import vocab

    claims = account.anonymous_claims()
    assert claims.age_band == "adult"
    for topic in ("crypto", "Bitcoin", "day trading"):
        assert not vocab.check(topic, claims.age_band)
        assert vocab.check(topic, "13-15"), "still barred to anyone on a minor band"


def test_a_false_claim_is_still_unsayable_to_the_default_reader():
    """The gate that actually protects an unknown reader, at their new band."""
    from app.safety import vocab

    claims = account.anonymous_claims()
    for text in ("risk-free", "guaranteed return", "guaranteed profit", "get rich"):
        assert vocab.check(text, claims.age_band), f"{text!r} became sayable"


def test_an_unknown_persona_falls_back_to_the_default_too():
    """A junk `?persona=` must resolve to the default, not to something else."""
    for junk in ("", "   ", "wizard", "ADULT", None):
        claims = account.anonymous_claims(junk)
        assert claims.persona == "guest", junk
        assert claims.age_band == "adult", junk


@pytest.mark.parametrize(
    ("picked", "band"),
    [("stella", "5-8"), ("orion", "13-15"), ("aurora", "adult"), ("nova", "adult")],
)
def test_the_picker_still_works_for_a_visitor(picked, band):
    """
    The safety is in the default, not in a lock.

    A parent reading about the programme before signing up picks Aurora and gets
    adult wording, which is the point of the picker. Deliberate: locking a
    signed-out visitor to the youngest band would read as broken to exactly the
    person the programme is trying to recruit.
    """
    claims = account.anonymous_claims(picked)

    assert claims.persona == picked
    assert claims.age_band == band


# ── the persona request ──────────────────────────────────────────────────────


def test_a_narrower_persona_is_granted():
    """An adult may prefer Nova's plainer register to Aurora's."""
    claims = account.derive(
        born=date(1990, 1, 1),
        is_minor=False,
        account_status="guardian",
        requested_persona="nova",
    )

    assert claims.persona == "nova"
    assert not claims.persona_request_refused


def test_a_wider_persona_is_refused_and_recorded():
    """A six-year-old asking for the guardian persona gets Stella."""
    claims = account.derive(
        born=date(2020, 1, 1),
        is_minor=True,
        account_status="prospect",
        requested_persona="aurora",
    )

    assert claims.persona == "stella"
    assert claims.persona_request_refused


def test_a_persona_that_grants_nothing_is_refused():
    """Narrower must still mean reachable."""
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


# ── the role ─────────────────────────────────────────────────────────────────


def test_a_guardian_account_gets_the_guardian_persona():
    claims = account.derive(
        born=date(1990, 1, 1),
        is_minor=False,
        account_status="guardian",
        role="guardian",
    )

    assert claims.persona == "aurora"
    assert "register_agent" in allowed_agents(
        claims.persona, claims.age_band, claims.account_status, user_id="derivation"
    )


def test_an_educator_gets_nova_without_asking_for_it_every_session():
    """The role picks the persona; the picker is no longer the only route to it."""
    claims = account.derive(
        born=date(1990, 1, 1),
        is_minor=False,
        account_status="prospect",
        role="educator",
    )

    assert claims.persona == "nova"


@pytest.mark.parametrize(
    ("born", "role", "expected"),
    [
        # A self-declared guardian in a teen band.
        (date(2009, 1, 1), "guardian", "orion"),
        # A self-declared educator in a teen band.
        (date(2012, 1, 1), "educator", "orion"),
        (date(2018, 1, 1), "guardian", "stella"),
        (date(2018, 1, 1), "educator", "stella"),
    ],
)
def test_a_role_can_never_widen_what_the_band_grants(born, role, expected):
    claims = account.derive(
        born=born,
        is_minor=True,
        account_status="prospect",
        role=role,
        today=date(2026, 8, 5),
    )

    assert claims.persona == expected


def test_a_role_narrows_before_a_request_narrows_again():
    """The two narrowings compose, and neither may undo the other's limit."""
    claims = account.derive(
        born=date(1990, 1, 1),
        is_minor=False,
        account_status="guardian",
        role="educator",          # aurora -> nova
        requested_persona="aurora",  # and back? no.
    )

    assert claims.persona == "nova"
    assert claims.persona_request_refused


def test_an_absent_role_behaves_exactly_as_before_the_column_existed():
    """Every row backfilled by migration 0017 is a `participant`."""
    for band_born, expected in (
        (date(2018, 1, 1), "stella"),  # 8  -> 5-8
        (date(2015, 1, 1), "kaleb"),  # 11 -> 9-12, and Kaleb is his own key now
        (date(2012, 1, 1), "orion"),  # 14 -> 13-15
        (date(2009, 1, 1), "orion"),  # 17 -> 16-18
        (date(1990, 1, 1), "aurora"),  # adult
    ):
        without = account.derive(
            born=band_born,
            is_minor=True,
            account_status="prospect",
            today=date(2026, 8, 5),
        )
        participant = account.derive(
            born=band_born,
            is_minor=True,
            account_status="prospect",
            role="participant",
            today=date(2026, 8, 5),
        )
        assert without.persona == participant.persona == expected


def test_persona_for_agrees_with_derive():
    """`sessions.to_session` shows the reader what `derive` will actually mint."""
    for band in sorted(account.DEFAULT_PERSONA):
        for role in ("participant", "guardian", "educator", None):
            shown = account.persona_for(band, role)
            assert allowed_agents(shown, band, "prospect", user_id="derivation"), (
                f"persona_for({band!r}, {role!r}) returned {shown!r}, which the "
                f"matrix grants no agents for"
            )
