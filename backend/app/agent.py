"""The ASPIRE agent: chat model + card tools + short-term memory.

This WAS agentic RAG -- the agent owned the retriever as a tool, decided for
itself whether to call it, and could call it more than once when the first
results were weak. As of P13-005 it is a fixed retrieve-then-answer chain, and
that was a deliberate trade for latency: the deciding call cost 876 ms at p50 and
2.6 s at p95 of time-to-first-token, and the corpus is 332 fixed rows that
retrieval finds on the first attempt 95% of the time.

What the agent still decides for itself is which turns are cards rather than
answers -- games and eligibility remain tools, because those genuinely are
choices. Retrieval was not: every factual question needed it, and the system
prompt said so in as many words.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel
from pydantic import Field as PydanticField

from app.config import Settings, get_settings
from app.db import database_enabled
from app.eligibility import ELIGIBILITY_TOOLS, eligibility_enabled
from app.games import GAME_TOOLS, games_enabled
from app.prompts import (
    ASPIRE_SYSTEM_PROMPT,
    ELIGIBILITY_INSTRUCTIONS,
    FOLLOW_UP_PROMPT,
    GAMES_INSTRUCTIONS,
    SIMPLE_MODE_INSTRUCTIONS,
    SUMMARY_PROMPT,
    TITLE_PROMPT,
)

logger = logging.getLogger(__name__)


def build_chat_model(settings: Settings | None = None):
    """Construct the configured chat model with provider-specific arguments."""
    settings = settings or get_settings()

    # "provider:model" string keeps the provider swappable from config alone.
    # temperature is omitted unless explicitly configured: the GPT-5 family rejects
    # any value but its default, so sending one would fail every request.
    model_kwargs = {}
    if settings.chat_temperature is not None:
        model_kwargs["temperature"] = settings.chat_temperature

    # Applied only for OpenAI, since it is an OpenAI-specific argument. Without it
    # the GPT-5 family refuses to use function tools -- see config for details.
    if settings.chat_model.startswith("openai:") and settings.openai_use_responses_api:
        model_kwargs["use_responses_api"] = True

    return init_chat_model(settings.chat_model, **model_kwargs)


# One checkpointer shared by every agent variant. Conversation memory belongs to
# the thread, not to the mode, so toggling "Explain it simply" mid-conversation
# must not strand the user in a thread the new agent has never seen.
#
# It replays the ENTIRE thread into the model on every turn -- including every
# ToolMessage carrying that turn's retrieved documents -- so the prompt grows
# without bound while the useful context does not. That is what
# MEMORY_WINDOW_ENABLED replaces: with the flag on, the caller assembles a
# window plus a summary itself (`app.memory.build_prompt`) and this is left out
# of the agent entirely.
#
# The two are mutually exclusive and must stay that way. A checkpointer AND
# caller-supplied history would send the saved thread plus the messages passed
# in -- every turn duplicated.
_CHECKPOINTER = InMemorySaver()


def build_agent(settings: Settings | None = None, *, simple_mode: bool = False):
    """Wire up the model, the card tools, and the shared checkpointer."""
    settings = settings or get_settings()
    model = build_chat_model(settings)

    system_prompt = ASPIRE_SYSTEM_PROMPT
    if simple_mode:
        system_prompt += SIMPLE_MODE_INSTRUCTIONS

    # Retrieval is NOT a tool any more (P13-005). It runs on the request path,
    # concurrently with the database work, and its results are in the prompt
    # before the model is called at all.
    #
    # That is what removes a whole model round trip from time-to-first-token. The
    # agent used to spend one call deciding to search, wait for the search, then
    # spend a second call writing the answer -- and `app/streaming.py` releases no
    # text until a tool has run, so the reader waited out both. With the corpus
    # already in the prompt an ordinary answer is one call.
    #
    # What is given up, and it is a real loss worth naming: the agent can no
    # longer search twice when the first results are thin, which the old
    # retriever tool description explicitly invited it to do. The corpus is 332
    # fixed rows and `evals/run.py` measures retrieval at 0.95 hit rate on the
    # first attempt, so the second search was rarely load-bearing -- but "rarely"
    # is not "never", and this is the trade.
    #
    # Games are additive: the tools and their prompt section appear together or
    # not at all, so a disabled module leaves no instructions describing tools
    # the agent does not have.
    tools = []
    if games_enabled():
        tools.extend(GAME_TOOLS)
        system_prompt += GAMES_INSTRUCTIONS

    # Same additive shape as the games block: the tool and its prompt section
    # appear together or not at all, so switching the module off never leaves
    # instructions describing a tool the agent does not have.
    if eligibility_enabled():
        tools.extend(ELIGIBILITY_TOOLS)
        system_prompt += ELIGIBILITY_INSTRUCTIONS

    # With the window off, the checkpointer holds multi-turn memory per
    # thread_id and the service behaves exactly as it always has. With it on,
    # the agent is stateless and history arrives with each invocation -- see the
    # note on _CHECKPOINTER for why it cannot be both.
    # AND a database, not just the flag. With the window on and no Postgres to
    # read history from, `load_context` returns nothing and the agent is handed a
    # bare question -- the conversation would lose its memory entirely rather
    # than merely windowing it. Gating on both means a database-less deployment
    # keeps working exactly as it does today.
    windowed = settings.memory_window_enabled and database_enabled()
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        **({} if windowed else {"checkpointer": _CHECKPOINTER}),
    )

    logger.info(
        "Agent ready (model=%s, k=%d, simple_mode=%s, games=%s, eligibility=%s, "
        "tools=%d, memory=%s)",
        settings.chat_model,
        settings.retriever_k,
        simple_mode,
        games_enabled(),
        eligibility_enabled(),
        len(tools),
        "window+summary" if windowed else "full-history checkpointer",
    )
    return agent


@lru_cache(maxsize=2)
def get_agent(simple_mode: bool = False):
    """Process-wide agent, one per mode. Both share `_CHECKPOINTER`."""
    return build_agent(simple_mode=simple_mode)


class _FollowUps(BaseModel):
    """Structured shape for the follow-up suggestion call."""

    questions: list[str] = PydanticField(
        description="Exactly two short follow-up questions in the user's voice.",
    )


@lru_cache(maxsize=1)
def _follow_up_model():
    return build_chat_model().with_structured_output(_FollowUps)


async def suggest_follow_ups(question: str, answer: str) -> list[str]:
    """Propose two next questions for the client's follow-up chips.

    Deliberately best effort: this is a small extra model call, and a suggestion
    failing is never a reason to fail the answer the user actually asked for.
    """
    try:
        result = await _follow_up_model().ainvoke(
            [
                {"role": "system", "content": FOLLOW_UP_PROMPT},
                {"role": "user", "content": f"User asked: {question}\n\nAssistant answered: {answer}"},
            ]
        )
    except Exception:
        logger.warning("Follow-up suggestion failed; returning none.", exc_info=True)
        return []

    return [q.strip() for q in result.questions if q.strip()][:2]


# Languages the title call will write in, mapped to the name the prompt uses.
# Mirrors the client's voice language options; anything unrecognised is English.
_TITLE_LANGUAGES = {"en": "English", "es": "Spanish", "fr": "French"}

# The model is asked for this exactly when the opening message carries no topic.
NO_TITLE = "NO_TITLE"


class _Title(BaseModel):
    """Structured shape for the conversation-title call."""

    title: str = PydanticField(
        description=(
            "3 to 6 words naming the specific thing asked, in sentence case, "
            f"at most 48 characters -- or exactly {NO_TITLE} if the opening "
            "message has no real subject."
        ),
    )


@lru_cache(maxsize=1)
def _title_model():
    return build_chat_model().with_structured_output(_Title)


async def suggest_title(question: str, answer: str, language: str = "en") -> str | None:
    """Name a conversation for the history list and the top bar.

    A separate, small, non-streaming call, deliberately kept off the /chat path:
    that response streams and is RAG-grounded, and a title leaking into the
    visible answer is worse than a title arriving late.

    Best effort in exactly the same way as `suggest_follow_ups`. Returns None
    when there is no usable title -- the model said NO_TITLE, the call failed, or
    the result came back empty -- and the client keeps its own fallback.
    """
    spoken = _TITLE_LANGUAGES.get(language, "English")
    try:
        result = await _title_model().ainvoke(
            [
                {"role": "system", "content": TITLE_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Language for the title: {spoken}\n\n"
                        f"User asked: {question}\n\n"
                        f"Assistant answered: {answer}"
                    ),
                },
            ]
        )
    except Exception:
        logger.warning("Title suggestion failed; falling back.", exc_info=True)
        return None

    title = (result.title or "").strip().strip("\"'").rstrip(".!?,;:")
    if not title or title.upper().replace(" ", "_") == NO_TITLE:
        return None
    # The prompt asks for 48; enforce it here too, because a prompt is a request
    # and this is the thing the layout actually depends on.
    return title[:48].strip()


@lru_cache(maxsize=1)
def _summary_model():
    return build_chat_model()


async def summarise_conversation(
    turns: list[tuple[str, str]], previous: str | None = None
) -> str | None:
    """Fold older turns into a running summary.

    Called only from the arq worker, never from a request. That is what makes
    the rolling window affordable: compression costs a model call, and a model
    call on the request path would move the latency rather than remove it.

    Best effort, like every other auxiliary call here. Returning None leaves the
    existing summary and `summarized_through_seq` untouched, so the same turns
    are retried on the next trigger rather than being silently lost.
    """
    if not turns:
        return None

    transcript = "\n\n".join(f"{role}: {content}" for role, content in turns)
    user_content = (
        f"Earlier summary:\n{previous}\n\nNew turns to fold in:\n{transcript}"
        if previous
        else f"Conversation so far:\n{transcript}"
    )

    try:
        result = await _summary_model().ainvoke(
            [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": user_content},
            ]
        )
    except Exception:
        logger.warning(
            "Conversation summarisation failed; keeping the previous summary.",
            exc_info=True,
        )
        return None

    content = result.content
    if isinstance(content, list):
        content = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    summary = (content or "").strip()
    return summary or None
