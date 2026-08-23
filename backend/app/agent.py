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


# --- Translating retrieved text on the way out ---

#: The languages chips and source labels are translated into.
_CHIP_LANGUAGES = {"es": "Spanish", "fr": "French"}


class _Translated(BaseModel):
    """Structured shape for the chip-translation call."""

    lines: list[str] = PydanticField(
        description=(
            "The translated lines, in the SAME ORDER and the SAME NUMBER as the "
            "input. Translate each line on its own; never merge, split, drop or "
            "reorder them."
        ),
    )


@lru_cache(maxsize=1)
def _translate_model():
    return build_chat_model().with_structured_output(_Translated)


_TRANSLATE_PROMPT = (
    "You translate short user-interface strings for a financial-education "
    "service run by the Government of Saint Kitts and Nevis, read by children "
    "and their guardians.\n\n"
    "Rules:\n"
    "- Return exactly as many lines as you were given, in the same order.\n"
    "- Keep each line short enough to sit on a button.\n"
    "- Keep it plain. These are read by children as young as five.\n"
    "- Do NOT translate: ASPIRE, EC$, the names of places, banks and people.\n"
    "- A question stays a question."
)


async def translate_lines(lines: list[str], language: str) -> list[str] | None:
    """Translate short UI strings, or None if the call failed or was refused.

    None rather than a partial list on purpose. A half-translated chip row --
    two Spanish, one English -- reads worse than three English ones, so the
    caller keeps the originals unless every line came back.
    """
    spoken = _CHIP_LANGUAGES.get(language)
    if not spoken or not lines:
        return None
    try:
        result = await _translate_model().ainvoke(
            [
                {"role": "system", "content": _TRANSLATE_PROMPT},
                {
                    "role": "user",
                    "content": f"Translate into {spoken}:\n"
                    + "\n".join(lines),
                },
            ]
        )
    except Exception:
        logger.warning("Chip translation failed; keeping the originals.", exc_info=True)
        return None

    out = [line.strip() for line in (result.lines or [])]
    # A model that dropped or invented a line cannot be used: the caller pairs
    # these back up by position.
    if len(out) != len(lines) or not all(out):
        logger.warning(
            "Chip translation returned %d lines for %d; keeping the originals.",
            len(out),
            len(lines),
        )
        return None
    return out


async def localise_lines(lines: list[str], language: str) -> list[str]:
    """`lines` in `language`, translating only what is not already cached.

    Returns the input unchanged for English, for an unknown language, or on any
    failure. This sits on the answer path, so it degrades to the status quo
    rather than costing anyone their chips.
    """
    if language not in _CHIP_LANGUAGES or not lines:
        return lines

    from app import cache

    known: dict[str, str] = {}
    for line in lines:
        hit = await cache.get_translation(line, language)
        if hit:
            known[line] = hit

    missing = [line for line in lines if line not in known]
    if missing:
        fresh = await translate_lines(missing, language)
        if fresh is None:
            # Nothing new could be translated. Rather than mix languages, only
            # use the cache if it happened to cover everything.
            if len(known) != len(lines):
                return lines
        else:
            for original, translated in zip(missing, fresh, strict=True):
                known[original] = translated
                await cache.put_translation(original, language, translated)

    return [known.get(line, line) for line in lines]


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
