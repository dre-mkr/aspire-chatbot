"""The one place an agent's message list is built."""

from __future__ import annotations

from typing import Any, Iterable

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.context.session_context import SessionContext
from app.prompting.global_rules import GLOBAL
from app.prompting.personas import persona_card

#: What the retrieved block is introduced with, in the human turn.
_CONTEXT_HEADING = "Reference material for this question:"

#: What the history block is introduced with.
_HISTORY_HEADING = "The conversation so far:"
_SUMMARY_HEADING = "Earlier in this conversation:"


def stable_prefix(context: SessionContext, agent_role: str) -> str:
    """The three layers that must not change within a session."""
    return "\n\n".join(
        part.strip()
        for part in (GLOBAL, persona_card(context.persona), agent_role)
        if part and part.strip()
    )


def _turn_context(context: SessionContext) -> str:
    """The per-turn system block: summary, then history verbatim."""
    blocks: list[str] = []
    if context.running_summary.strip():
        blocks.append(f"{_SUMMARY_HEADING}\n{context.running_summary.strip()}")
    if context.recent_turns:
        lines = "\n".join(f"{turn.role}: {turn.text}" for turn in context.recent_turns)
        blocks.append(f"{_HISTORY_HEADING}\n{lines}")

    # Facts the reader should not have to repeat.
    facts = [f"Today is {context.now.strftime('%A %d %B %Y')}."]
    if context.display_name:
        facts.append(f"You are speaking with {context.display_name}.")
    blocks.append(" ".join(facts))

    return "\n\n".join(blocks)


def _retrieved_block(chunks: Iterable[Any]) -> str:
    """Retrieved rows, formatted for the human turn."""
    lines = [
        f"[{getattr(chunk, 'kb_id', '?')}] {getattr(chunk, 'content', '').strip()}"
        for chunk in chunks
        if getattr(chunk, "content", "").strip()
    ]
    return f"{_CONTEXT_HEADING}\n" + "\n\n".join(lines) if lines else ""


def build_messages(
    *,
    context: SessionContext,
    agent_role: str,
    user_text: str,
    retrieved: Iterable[Any] = (),
    extra_instruction: str | None = None,
) -> list[BaseMessage]:
    """The message list for one agent call."""
    messages: list[BaseMessage] = [SystemMessage(content=stable_prefix(context, agent_role))]

    turn_context = _turn_context(context)
    if extra_instruction and extra_instruction.strip():
        turn_context = f"{turn_context}\n\n{extra_instruction.strip()}".strip()
    if turn_context:
        messages.append(SystemMessage(content=turn_context))

    human = user_text.strip()
    retrieved_block = _retrieved_block(retrieved)
    if retrieved_block:
        human = f"{human}\n\n{retrieved_block}" if human else retrieved_block
    messages.append(HumanMessage(content=human))

    return messages
