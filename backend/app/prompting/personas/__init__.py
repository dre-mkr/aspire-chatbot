"""One card per persona, shared by every agent that speaks to a reader.

Markdown files rather than Python constants, because a persona card is copy. It
is reviewed by whoever owns the programme's voice, not by whoever owns the graph,
and a `.md` file is something they can open.

## The cards are authored copy and need review

The band data underneath them is real -- the word caps come from
`safety_out.WORD_CAPS` (35 words at 5-8, 70 at 9-12, 120 at 13-15, 180 at 16-18)
and the vocabulary rules from `safety.vocab`, which is what actually enforces
them. The register descriptions, example choices and local references are
authored, and are flagged here as such: nothing in them states a programme rule,
a figure or a rate, but the voice they describe has not been signed off by
anybody yet.

## Registration and escalation get one too

Track P requires every agent that talks to a user to carry a persona card, and
the diagnosis found registration and escalation carrying none -- which was
partly vacuous, since neither generated prose at all. Now that `build_messages`
is the one construction path, an agent that starts generating gets the card for
free rather than having to remember it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final

_DIR: Final[Path] = Path(__file__).resolve().parent

#: Which card a persona gets. `stella` and `orion` are the two child-facing
#: mascots; `aurora` and `nova` are the two adult roles.
KNOWN: Final[frozenset[str]] = frozenset({"stella", "orion", "aurora", "nova"})

#: The card used when the persona is missing or unrecognised.
#:
#: `aurora` rather than `stella`, and the direction matters: an unknown persona
#: given the children's card would be an adult addressed as a seven-year-old,
#: while an unknown persona given the adult card is a child addressed plainly.
#: Neither is right, and only one of them is also a band violation --
#: `safety_out` catches over-long prose for a child band regardless of the card,
#: so the adult card fails into a gate that exists.
FALLBACK: Final[str] = "aurora"


@lru_cache(maxsize=8)
def persona_card(persona: str | None) -> str:
    """The card for this persona, verbatim from its file.

    Cached: read on every turn, and the files do not change while the process
    runs. `lru_cache` rather than a module-level dict so a missing file raises
    where it is used rather than at import.
    """
    name = (persona or "").strip().lower()
    if name not in KNOWN:
        name = FALLBACK
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
