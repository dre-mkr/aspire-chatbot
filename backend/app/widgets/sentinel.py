"""The markers that separate a widget from the prose around it."""

from __future__ import annotations

import re

#: Deliberately not brackets or backticks — not characters a model reaches for on its own.
OPEN = "⟦widget⟧"
CLOSE = "⟦/widget⟧"

#: Non-greedy, and DOTALL because composed JSON is pretty-printed across lines.
_BLOCK = re.compile(re.escape(OPEN) + r"(.*?)" + re.escape(CLOSE), re.DOTALL)


def split(text: str) -> tuple[str, list[str]]:
    """The prose with every widget block removed, and those blocks in order."""
    blocks = [match.group(0) for match in _BLOCK.finditer(text)]
    if not blocks:
        return text, []

    prose = _BLOCK.sub(" ", text)
    prose = re.sub(r"[ \t]{2,}", " ", prose)
    prose = re.sub(r"\n{3,}", "\n\n", prose)
    return prose.strip(), blocks


def reattach(prose: str, blocks: list[str]) -> str:
    """Prose followed by its widget blocks."""
    if not blocks:
        return prose
    return "\n\n".join([prose.strip(), *blocks]).strip()


def strip(text: str) -> str:
    """Just the prose. For callers that only need to measure or read it."""
    return split(text)[0]


def count(text: str) -> int:
    """How many complete widget blocks are in this message."""
    return len(_BLOCK.findall(text))
