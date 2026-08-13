"""Reading a LangChain message, whichever shape its content arrived in."""

from __future__ import annotations

from typing import Any

__all__ = ["text_of"]


def text_of(message: Any) -> str:
    """The message's text, flattening the multimodal block form to the parts that are text."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""
