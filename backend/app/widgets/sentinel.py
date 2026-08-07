"""The markers that separate a widget from the prose around it.

Defined here rather than in the transport because two very different pieces of
code need the same answer to "which part of this message is a widget?", and
they need it for opposite reasons:

  * `graph/stream_interceptor.py` reads them off a TOKEN STREAM, incrementally,
    where a marker can be split across chunks. That is the hard case and it has
    its own buffering machine.
  * `graph/nodes/safety_out.py` reads them off a FINISHED message, to gate the
    prose without gating the JSON.

The second one is why this module exists. `safety_out` counts words against a
band cap -- thirty-five for a six-year-old -- and a composed widget is a few
hundred characters of JSON. Left in the string, it puts every widget-bearing
lesson turn over the cap, triggers the shorten re-prompt, and the model rewrites
the widget into prose or drops it. The widget never reaches the child and the
log says the reply was too long, which is true and useless.

## Splitting is not the same as removing

`split` returns the prose AND the blocks, and `reattach` is the other half.
`safety_out` puts the widgets back when it changed the prose and returns the
original string untouched when it did not -- so a clean turn keeps the widget
exactly where the model placed it, and only a rewritten turn pays the cost of
the widget moving to the end. Dropping the blocks would be simpler and would
mean the gates silently delete widgets, which is the failure this module is
here to prevent rather than a smaller version of it.
"""

from __future__ import annotations

import re

#: Deliberately not angle brackets, not backticks, and not any character a
#: model reaches for on its own. `widgets/schemas.py` rejects `<` and `>` in
#: every widget string, so a marker built from them could not survive its own
#: validator; these two are outside the range anything else in the product uses,
#: which is what makes finding them unambiguous.
OPEN = "⟦widget⟧"
CLOSE = "⟦/widget⟧"

#: Non-greedy, and DOTALL because composed JSON is pretty-printed across lines.
#: An unterminated OPEN matches nothing and is left in the prose, where the
#: gates will treat it as the stray characters it is -- the transport has the
#: same rule, for the same reason: a half-widget is not a widget.
_BLOCK = re.compile(re.escape(OPEN) + r"(.*?)" + re.escape(CLOSE), re.DOTALL)


def split(text: str) -> tuple[str, list[str]]:
    """The prose with every widget block removed, and those blocks in order.

    The prose is whitespace-collapsed at the seams only: removing a block from
    the middle of a paragraph leaves a double space, and a double space is a
    word-count artefact rather than something the writer put there.
    """
    blocks = [match.group(0) for match in _BLOCK.finditer(text)]
    if not blocks:
        return text, []

    prose = _BLOCK.sub(" ", text)
    prose = re.sub(r"[ \t]{2,}", " ", prose)
    prose = re.sub(r"\n{3,}", "\n\n", prose)
    return prose.strip(), blocks


def reattach(prose: str, blocks: list[str]) -> str:
    """Prose followed by its widget blocks.

    Order among the blocks is preserved; their position relative to the prose
    is not, because there is nothing left to anchor them to once the prose has
    been rewritten. A widget at the end of a re-prompted reply is worth having;
    it is the only outcome here that is not a deletion.
    """
    if not blocks:
        return prose
    return "\n\n".join([prose.strip(), *blocks]).strip()


def strip(text: str) -> str:
    """Just the prose. For callers that only need to measure or read it."""
    return split(text)[0]


def count(text: str) -> int:
    """How many complete widget blocks are in this message."""
    return len(_BLOCK.findall(text))
