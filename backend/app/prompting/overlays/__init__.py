"""Personality overlays: how the reader wants to be engaged.

An overlay changes the ENGAGEMENT MOVES only. Facts, red lines, CARE, the
gates and every register cap stay exactly as the persona card sets them --
the lint suite asserts the overlay files cannot carry a rate, a projection
or a withdrawal promise. Chosen by the reader, stored as a preference,
appended to the prompt after the persona card.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final

_DIR: Final[Path] = Path(__file__).resolve().parent

#: Which bands may use each overlay. The Professor never speaks below 13-15;
#: the Storyteller and the Hype stop before adulthood is condescended to.
OVERLAY_BANDS: Final[dict[str, frozenset[str]]] = {
    "coach": frozenset(['13-15', '16-18', '9-12', 'adult']),
    "limer": frozenset(['13-15', '16-18', '9-12', 'adult']),
    "professor": frozenset(['13-15', '16-18', 'adult']),
    "storyteller": frozenset(['13-15', '5-8', '9-12']),
    "hype": frozenset({"5-8", "9-12", "13-15", "16-18", "adult"}),
    "quiet": frozenset(['13-15', '16-18', '5-8', '9-12', 'adult']),
    "unbothered": frozenset({"16-18"}),
    "hustler": frozenset(['13-15', '16-18', '9-12', 'adult']),
}

KNOWN_OVERLAYS: Final[frozenset[str]] = frozenset(OVERLAY_BANDS)


@lru_cache(maxsize=16)
def _text(overlay: str) -> str:
    return (_DIR / f"{overlay}.md").read_text(encoding="utf-8").strip()


def overlay_block(overlay: str | None, age_band: str | None) -> str:
    """The overlay's prompt block, or "" when unset or barred for this band."""
    key = (overlay or "").strip().lower()
    if key not in KNOWN_OVERLAYS:
        return ""
    if (age_band or "") not in OVERLAY_BANDS[key]:
        return ""
    return (
        _text(key)
        + "\n- Speak the reader's language. The personality survives translation: "
        "in Spanish or French keep the same energy and register; dialect lines "
        "soften to warm, natural standard Spanish or French rather than being "
        "translated word for word."
        # THE WHOLE ANSWER, NOT THE FIRST SENTENCE.
        #
        # Measured on the live site, 25 Aug: the same question put to Hype, the
        # Professor and the Limer came back with three different opening
        # metaphors and near-identical bodies. The overlay was applied -- none
        # of the three is band-barred at 16-18 -- and the model was spending it
        # all on the first line, then reverting to corpus prose. A reader
        # switching personality could not tell that anything had changed.
        + "\n- CARRY IT THROUGH, and carry it through NAMED THINGS. A voice "
        "spent on an opening line with neutral prose behind it is not a "
        "personality, it is a greeting. Measured: the same question put to "
        "three personalities came back with three different first sentences "
        "and near-identical bodies. These are the dimensions it moves:\n"
        "  - the opening, and the closing line or invitation\n"
        "  - sentence rhythm and length\n"
        "  - the KIND of analogy reached for, and what it is drawn from\n"
        "  - vocabulary, including how much slang or formality is allowed\n"
        "  - how it interacts: question-led, statement-led, challenge-led\n"
        "  - what the follow-up offers, and how hard it pushes\n"
        "  - humour, and how much of it\n"
        "A reader who read only your LAST sentence should still know which "
        "personality they chose.\n"
        "- AND THESE IT NEVER MOVES: a figure, a date, a rule, a citation, a "
        "source, a safety gate or a word cap. Those are identical whoever is "
        "speaking. The personality is how the answer sounds, never what is "
        "true in it, and a reader who switches personality mid-question must "
        "get the same facts back in a different voice."
    )
