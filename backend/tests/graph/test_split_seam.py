"""The compatibility seam that stands between the Kaleb split and a week-long outage.

`stella` used to be valid at both child bands. It is valid at 5-8 alone now,
because `kaleb` took 9-12 with him. That is correct going forward and wrong for
every token already issued: those still say `stella` with band `9-12`, and the
new rows answer that pair with an empty list -- no QA agent, no learn agent, no
escalation. Nothing raises. The assistant simply stops being able to answer.

Three facts make it worse than it sounds, and each has a test below:

  * `TOKEN_TTL` is SEVEN DAYS, so a token minted the week before cutover is
    still valid the week after. Not a switchover blip -- a rolling outage.
  * `stella/9-12` is the ONLY pair that newly returns nothing. Every other empty
    row was already empty before the split. So the blast radius is narrow and
    lands precisely on 9-to-12-year-olds: the cohort the split was built for.
  * The seam looks disposable. It is one entry in one dict, and its docstring is
    longer than its body, which is exactly the shape of a thing somebody tidies
    away on a quiet afternoon.

If you are here because a test failed after deleting `_SPLIT`: that is this file
working. The seam may be removed once no token issued before the deploy can
still be in play -- at least `TOKEN_TTL` after cutover, on the same terms as
`_RENAMED`. Not the morning after.
"""

from __future__ import annotations

import app.domain as domain
from app.graph.access import allowed_agents
from app.graph.identity import TOKEN_TTL
from app.graph.state import AGE_BANDS


def _agents(persona: str, band: str) -> list[str]:
    return allowed_agents(persona, band, "beneficiary", user_id="u")


class TestTheSeamExists:
    def test_the_old_pair_still_maps(self) -> None:
        assert domain._SPLIT[("stella", "9-12")] == "kaleb"

    def test_it_composes_with_the_rename_seam(self) -> None:
        """A token can be old enough to carry BOTH an old name and an old band."""
        assert domain.normalise_persona_band("everyone", "9-12") == "guest"
        assert domain.normalise_persona_band("stella", "9-12") == "kaleb"
        assert domain.normalise_persona_band("stella", "5-8") == "stella"

    def test_it_does_not_touch_the_band_that_did_not_move(self) -> None:
        assert domain.normalise_persona_band("stella", "5-8") == "stella"


class TestWhatTheSeamIsHoldingUp:
    def test_a_token_minted_before_the_split_keeps_every_agent(self) -> None:
        """The claim the whole seam exists to make true."""
        assert _agents("stella", "9-12") == _agents("kaleb", "9-12")
        assert _agents("stella", "9-12"), "an old token must not resolve to nothing"

    def test_without_the_seam_that_token_gets_nothing(self, monkeypatch) -> None:
        """The outage, demonstrated rather than asserted about.

        This is the test to read if the seam looks unnecessary.
        """
        monkeypatch.setattr(domain, "_SPLIT", {})
        assert _agents("stella", "9-12") == [], (
            "if this no longer fails, the access rows changed and the seam's "
            "purpose should be re-derived before anyone deletes it"
        )

    def test_it_is_the_only_pair_that_moved(self, monkeypatch) -> None:
        """Blast radius, measured. Narrow, and the worst possible one."""
        monkeypatch.setattr(domain, "_SPLIT", {})
        newly_empty = [
            (persona, band)
            for persona in ("stella", "orion", "aurora", "nova", "guest")
            for band in AGE_BANDS
            if not _agents(persona, band)
            # Pairs that were already impossible before the split: a persona is
            # only ever valid at the bands it has cards for.
            and (persona, band) not in _ALREADY_EMPTY
        ]
        assert newly_empty == [("stella", "9-12")]

    def test_the_exposure_window_is_a_week_not_a_moment(self) -> None:
        """Why this cannot be handled by deploying at a quiet hour."""
        assert TOKEN_TTL.days >= 7, (
            "if the token lifetime changed, the seam's minimum lifetime changes "
            "with it -- it must outlive the longest-lived token by definition"
        )


#: Pairs that returned nothing before the split as well, so they are not
#: evidence of anything. `stella` was always child-bands-only, `orion` always
#: teen-only, and so on.
_ALREADY_EMPTY = frozenset(
    {
        ("stella", "13-15"),
        ("stella", "16-18"),
        ("stella", "adult"),
        ("orion", "5-8"),
        ("orion", "9-12"),
        ("orion", "adult"),
    }
)
