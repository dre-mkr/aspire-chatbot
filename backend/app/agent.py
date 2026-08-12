"""The chat model, and the two small calls that are not turns."""

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
    """The "provider:model" string this persona's turns run on."""
    settings = settings or get_settings()
    return settings.chat_model_by_persona.get(persona or "", settings.chat_model)


def resolve_max_tokens_for(persona: str | None, settings: Settings | None = None) -> int | None:
    """The output-token cap for this persona's turns, or None for uncapped."""
    settings = settings or get_settings()
    caps = settings.max_tokens_by_persona
    return caps.get(persona or "") or caps.get("") or None


def build_chat_model(settings: Settings | None = None, *, model: str | None = None,
                     max_tokens: int | None = None):
    """Construct the configured chat model with provider-specific arguments."""
    settings = settings or get_settings()
    chosen = model or settings.chat_model

    # "provider:model" string keeps the provider swappable from config alone.
    model_kwargs = {}
    if settings.chat_temperature is not None:
        model_kwargs["temperature"] = settings.chat_temperature

    # A cap on output, not a style control.
    if max_tokens is not None:
        model_kwargs["max_tokens"] = max_tokens

    # Applied only for OpenAI, since it is an OpenAI-specific argument.
    if chosen.startswith("openai:") and settings.openai_use_responses_api:
        model_kwargs["use_responses_api"] = True

    if chosen.startswith("openai:"):
        # Ask for usage in the stream, so the turn can report the provider's own token counts.
        model_kwargs["stream_usage"] = True

    return init_chat_model(chosen, **model_kwargs)


# Languages the title call will write in, mapped to the name the prompt uses.
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
    """Name a conversation for the history list and the top bar."""
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
    # The prompt asks for 48 characters; enforce it here too, because a prompt is only a request.
    return title[:48].strip()


@lru_cache(maxsize=1)
def _summary_model():
    return build_chat_model()


async def summarise_conversation(
    turns: list[tuple[str, str]], previous: str | None = None
) -> str | None:
    """Fold older turns into a running summary."""
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
