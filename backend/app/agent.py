"""The ASPIRE agent: chat model + retriever tool + short-term memory.

This is agentic RAG, not a fixed retrieve-then-answer chain. The agent owns the
retriever as a tool and decides for itself whether to call it, and may call it
more than once per turn if the first results are weak.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools.retriever import create_retriever_tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel
from pydantic import Field as PydanticField

from app.config import Settings, get_settings
from app.games import GAME_TOOLS, games_enabled
from app.prompts import (
    ASPIRE_SYSTEM_PROMPT,
    FOLLOW_UP_PROMPT,
    GAMES_INSTRUCTIONS,
    RETRIEVER_TOOL_DESCRIPTION,
    RETRIEVER_TOOL_NAME,
    SIMPLE_MODE_INSTRUCTIONS,
    TITLE_PROMPT,
)
from app.rag import build_retriever, get_vector_store

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
_CHECKPOINTER = InMemorySaver()


def build_agent(settings: Settings | None = None, *, simple_mode: bool = False):
    """Wire up the model, the retrieval tool, and the shared checkpointer."""
    settings = settings or get_settings()
    model = build_chat_model(settings)

    retriever = build_retriever(get_vector_store(), settings)
    retriever_tool = create_retriever_tool(
        retriever,
        name=RETRIEVER_TOOL_NAME,
        description=RETRIEVER_TOOL_DESCRIPTION,
        # Returns (text_for_the_model, list[Document]). The Document list rides
        # along on ToolMessage.artifact, which is how /chat reports the exact
        # snippets the agent saw without re-running retrieval.
        response_format="content_and_artifact",
    )

    system_prompt = ASPIRE_SYSTEM_PROMPT
    if simple_mode:
        system_prompt += SIMPLE_MODE_INSTRUCTIONS

    # Games are additive: the tools and their prompt section appear together or
    # not at all, so a disabled module leaves no instructions describing tools
    # the agent does not have.
    tools = [retriever_tool]
    if games_enabled():
        tools.extend(GAME_TOOLS)
        system_prompt += GAMES_INSTRUCTIONS

    # In-memory checkpointer: multi-turn memory per thread_id, cleared on restart.
    # Phase 1 only -- swap for a persistent saver when conversations must survive.
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=_CHECKPOINTER,
    )

    logger.info(
        "Agent ready (model=%s, k=%d, simple_mode=%s, games=%s, tools=%d)",
        settings.chat_model,
        settings.retriever_k,
        simple_mode,
        games_enabled(),
        len(tools),
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
