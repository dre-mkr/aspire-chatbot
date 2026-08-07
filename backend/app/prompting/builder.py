"""The one place an agent's message list is built.

    system   GLOBAL + PERSONA_CARD + AGENT_ROLE      <- stable, cacheable prefix
    ─────────────────────────────── cache breakpoint ───────────────────────────
    system   running summary, then the last six turns verbatim
    human    this turn, then any retrieved chunks

## Why the order is this order, and not a matter of taste

The prefix has to be byte-identical across turns of a session or a provider
cannot serve it from cache. That single requirement decides everything above:

  * GLOBAL, the persona card and the agent role are the same strings on turn one
    and turn nine, so they go first and together.
  * The summary and the history change every turn, so they go after the
    breakpoint. They are still `system` because they are context rather than
    something the reader said this turn.
  * **Retrieved chunks go in the HUMAN turn.** They change on every single turn
    and they are large. `qa/nodes.py:485` put them in the system block via
    `GENERATE_SYSTEM.format(context=...)`, which means the Q&A agent's system
    prefix has never been the same twice and has therefore never been cacheable
    at all -- on the one agent that makes the most calls.

## History was missing entirely

The diagnosis found no agent LLM call receiving any conversation history:
`qa/nodes.py:495` and `learn/teach.py:306` both build `[System, Human]` from
scratch, and `memory.build_prompt` -- which assembles summary, history and
context properly -- has no caller in `app/`. QA survives because
`rewrite_query` folds context into the search query, so its retrieval sees the
thread even though its generation does not.

That is why `recent_turns` is not optional here. An agent that wants no history
passes a context with none; there is no flag to leave it out and forget.
"""

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
    """The three layers that must not change within a session.

    Joined with a blank line and nothing interpolated. Anything varying per turn
    -- a date, a name, a mastery figure -- belongs below the breakpoint, because
    one interpolated value here costs the cache hit for the whole prefix.
    """
    return "\n\n".join(
        part.strip()
        for part in (GLOBAL, persona_card(context.persona), agent_role)
        if part and part.strip()
    )


def _turn_context(context: SessionContext) -> str:
    """The per-turn system block: summary, then history verbatim.

    Returns "" when there is neither, so an opening turn adds no empty block --
    a blank `system` message is a token cost and a thing for a model to wonder
    about.
    """
    blocks: list[str] = []
    if context.running_summary.strip():
        blocks.append(f"{_SUMMARY_HEADING}\n{context.running_summary.strip()}")
    if context.recent_turns:
        lines = "\n".join(f"{turn.role}: {turn.text}" for turn in context.recent_turns)
        blocks.append(f"{_HISTORY_HEADING}\n{lines}")

    # Facts the reader should not have to repeat. Deliberately short and
    # deliberately not identity: the date, because no prompt in the product had
    # it and every deadline question needs it, and the name only when there is
    # one to use.
    # `%d` rather than `%-d`: the latter is not portable to Windows, and a
    # zero-padded day is not worth a platform probe on every turn.
    facts = [f"Today is {context.now.strftime('%A %d %B %Y')}."]
    if context.display_name:
        facts.append(f"You are speaking with {context.display_name}.")
    blocks.append(" ".join(facts))

    return "\n\n".join(blocks)


def _retrieved_block(chunks: Iterable[Any]) -> str:
    """Retrieved rows, formatted for the human turn.

    `[id] content`, the same shape `qa/nodes.py` used in the system block, so
    moving them changes their position and not their appearance to the model --
    citations keep working because the ids are still there in the same form.
    """
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
    """The message list for one agent call.

    `extra_instruction` is appended to the per-turn system block, not to the
    prefix -- it is for things like a composition instruction for a widget, which
    is present on some turns and absent on others and would break the cache if it
    sat above the breakpoint.
    """
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
