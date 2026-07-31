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
from app.prompts import (
    ASPIRE_SYSTEM_PROMPT,
    FOLLOW_UP_PROMPT,
    RETRIEVER_TOOL_DESCRIPTION,
    RETRIEVER_TOOL_NAME,
    SIMPLE_MODE_INSTRUCTIONS,
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

    # In-memory checkpointer: multi-turn memory per thread_id, cleared on restart.
    # Phase 1 only -- swap for a persistent saver when conversations must survive.
    agent = create_agent(
        model=model,
        tools=[retriever_tool],
        system_prompt=system_prompt,
        checkpointer=_CHECKPOINTER,
    )

    logger.info(
        "Agent ready (model=%s, k=%d, simple_mode=%s)",
        settings.chat_model,
        settings.retriever_k,
        simple_mode,
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
