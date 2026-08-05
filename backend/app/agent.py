"""The chat model, and the two small calls that are not turns.

This file used to build the agent. It does not any more: the agent is the graph
(`app/graph/main_graph.py`), and every turn goes through it. What is left here
is what the graph and the workers both need and neither owns --

    build_chat_model     the configured answer model, per persona
    suggest_title        names a conversation, off the turn path
    summarise_conversation   folds old turns into a summary, after the stream

-- plus the two `resolve_*_for` lookups that decide which model a persona's
turns run on.

## What went, and where

`build_agent` / `get_agent` are gone with `/chat`. The single system prompt they
carried (`ASPIRE_SYSTEM_PROMPT` plus the games and eligibility tool sections) is
replaced by per-agent prompts inside the subgraphs, which is the change that
makes an age band mean something: one prompt for every reader from five to
adult was the thing the band ladder could not be built on top of.

`suggest_follow_ups` is gone too, and its absence is a saving rather than a
loss. It was a second model call per turn, shown only the question and the
answer, and it produced two guesses at what to ask next. The agents now emit
`quick_replies` from what they actually did -- the lesson's next step, the
registration slot they are waiting on, the concept a Q&A answer touched -- for
no extra call and with information the follow-up model never had.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain.chat_models import init_chat_model
from pydantic import BaseModel
from pydantic import Field as PydanticField

from app.config import Settings, get_settings
from app.prompts import SUMMARY_PROMPT, TITLE_PROMPT

logger = logging.getLogger(__name__)


def resolve_model_for(persona: str | None, settings: Settings | None = None) -> str:
    """The "provider:model" string this persona's turns run on.

    One dict lookup with `chat_model` as the fallback -- the whole point of
    `chat_model_by_persona` is that this is the only place that reads it, so
    routing is tuned in config and never in scattered conditionals.
    """
    settings = settings or get_settings()
    return settings.chat_model_by_persona.get(persona or "", settings.chat_model)


def resolve_max_tokens_for(persona: str | None, settings: Settings | None = None) -> int | None:
    """The output-token cap for this persona's turns, or None for uncapped.

    The "" entry is the fallback for every persona without one of its own, so a
    single `{"": 4096}` caps everybody and per-persona entries only exist to
    differ from it.
    """
    settings = settings or get_settings()
    caps = settings.max_tokens_by_persona
    return caps.get(persona or "") or caps.get("") or None


def build_chat_model(settings: Settings | None = None, *, model: str | None = None,
                     max_tokens: int | None = None):
    """Construct the configured chat model with provider-specific arguments.

    `model` overrides `settings.chat_model`; the auxiliary calls (follow-ups,
    title, summary) pass nothing and keep the default, so persona routing can
    never change what a title or summary is written by.
    """
    settings = settings or get_settings()
    chosen = model or settings.chat_model

    # "provider:model" string keeps the provider swappable from config alone.
    # temperature is omitted unless explicitly configured: the GPT-5 family rejects
    # any value but its default, so sending one would fail every request.
    model_kwargs = {}
    if settings.chat_temperature is not None:
        model_kwargs["temperature"] = settings.chat_temperature

    # A cap on output, not a style control. langchain-openai maps `max_tokens`
    # to the parameter the Responses API expects, so one name covers both routes.
    if max_tokens is not None:
        model_kwargs["max_tokens"] = max_tokens

    # Applied only for OpenAI, since it is an OpenAI-specific argument. Without it
    # the GPT-5 family refuses to use function tools -- see config for details.
    if chosen.startswith("openai:") and settings.openai_use_responses_api:
        model_kwargs["use_responses_api"] = True

    if chosen.startswith("openai:"):
        # Ask for usage in the stream, so the turn can report the provider's own
        # input-token count and prefix-cache reads (P14-A). Without it the chat
        # completions route reports no usage on streamed responses at all.
        model_kwargs["stream_usage"] = True

    return init_chat_model(chosen, **model_kwargs)


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

    Called from `turn.summarise_thread`, after the stream has closed -- never
    from inside a turn. That is what makes the rolling window affordable:
    compression costs a model call, and a model call before `done` would leave
    the reader looking at a finished answer with no sources and no chips for as
    long as it took.

    It used to run in the arq worker, writing `conversations.summary`. The
    summary lives in the graph's checkpoint now, so the caller moved and the job
    was deleted -- see `app/jobs.py`.

    Best effort, like every other auxiliary call here. Returning None leaves the
    existing summary untouched, so the same turns are retried on the next
    trigger rather than being silently lost.
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
