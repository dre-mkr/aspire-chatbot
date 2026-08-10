"""Prompt tokens per turn, with the memory window off and on.

Run:  python -m scripts.measure_prompt_tokens

No API key and no database needed: this counts tokens with the same encoder the
service uses, over a modelled conversation.

The model of the CURRENT behaviour is the important part and is deliberately
faithful rather than flattering. The checkpointer replays the whole thread, and
a thread holds more than the visible turns: each one also leaves behind the
assistant's tool-call message and the ToolMessage carrying that turn's retrieved
documents, and every one of those is re-sent on every later turn. Leaving them
out would understate the current cost by roughly a third and make the change
look better than it is. They are counted.

Turn sizes come from the real corpus: `data/knowledge_base.csv` chunks measure
38 tokens on average, and retrieval returns `retriever_k` of them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import (  # noqa: E402
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.config import get_settings  # noqa: E402
from app.db.repository import ConversationContext  # noqa: E402
from app.memory import build_prompt, count_tokens  # noqa: E402
from app.prompts import ASPIRE_SYSTEM_PROMPT, GAMES_INSTRUCTIONS  # noqa: E402

# Measured from the real knowledge base and a typical exchange.
QUESTION_TOKENS = 18
ANSWER_TOKENS = 210
TOOL_RESULT_TOKENS = 4 * 38  # retriever_k chunks at the corpus mean
TOOL_CALL_TOKENS = 28
SUMMARY_TOKENS = 190  # SUMMARY_PROMPT caps the summary at 150 words


class _Turn:
    __slots__ = ("role", "content", "seq")

    def __init__(self, role: str, content: str, seq: int = 0):
        self.role, self.content, self.seq = role, content, seq


def _words(tokens: int) -> str:
    return " ".join(["saving"] * tokens)


def current_prompt_tokens(turns: int, system_tokens: int) -> int:
    """What the checkpointer sends on turn `turns`."""
    messages = [SystemMessage(content=_words(system_tokens))]
    for _ in range(turns):
        messages.append(HumanMessage(content=_words(QUESTION_TOKENS)))
        messages.append(AIMessage(content=_words(TOOL_CALL_TOKENS)))
        messages.append(
            ToolMessage(content=_words(TOOL_RESULT_TOKENS), tool_call_id="x")
        )
        messages.append(AIMessage(content=_words(ANSWER_TOKENS)))
    messages.append(HumanMessage(content=_words(QUESTION_TOKENS)))
    return count_tokens(messages)


def windowed_prompt_tokens(turns: int, system_tokens: int, window: int) -> int:
    """What is sent with the window on: system + summary + window + question."""
    visible = min(turns * 2, window)
    recent = [
        _Turn(
            "user" if i % 2 == 0 else "assistant",
            _words(QUESTION_TOKENS if i % 2 == 0 else ANSWER_TOKENS),
            i + 1,
        )
        for i in range(visible)
    ]
    context = ConversationContext(
        # Nothing to summarise until messages have fallen out of the window.
        summary=_words(SUMMARY_TOKENS) if turns * 2 > window else None,
        recent=recent,
        older_turn_count=max(0, turns * 2 - window),
    )
    # The system prompt is attached by create_agent, outside build_prompt, so it
    # is added here to keep both columns measuring the same whole.
    return build_prompt(_words(QUESTION_TOKENS), context).tokens + system_tokens


def main() -> None:
    settings = get_settings()
    window = settings.memory_window_turns
    system_tokens = count_tokens(ASPIRE_SYSTEM_PROMPT) + count_tokens(
        GAMES_INSTRUCTIONS
    )

    print(f"encoding       : {settings.token_encoding}")
    print(f"system prompt  : {system_tokens} tokens (instructions + games)")
    print(f"memory window  : {window} messages")
    print(f"flag currently : MEMORY_WINDOW_ENABLED={settings.memory_window_enabled}")
    print()
    print(f"{'turn':>5}  {'flag off':>9}  {'flag on':>9}  {'saved':>9}  {'saved %':>8}")
    print(f"{'-' * 5}  {'-' * 9}  {'-' * 9}  {'-' * 9}  {'-' * 8}")

    for turn in (1, 2, 3, 5, 10, 20, 40):
        before = current_prompt_tokens(turn, system_tokens)
        after = windowed_prompt_tokens(turn, system_tokens, window)
        saved = before - after
        pct = 100.0 * saved / before if before else 0.0
        print(f"{turn:>5}  {before:>9,}  {after:>9,}  {saved:>9,}  {pct:>7.1f}%")

    print()
    print(
        "'flag on' stops growing once the conversation exceeds the window;\n"
        "'flag off' grows linearly and without bound."
    )


if __name__ == "__main__":
    main()
