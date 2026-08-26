"""LangSmith tracing: off by default, redacted by default, useful either way.

WHY THIS FILE EXISTS AT ALL, when the skill says LangGraph tracing is two
environment variables. Because for this product those two variables would ship
children's messages to a third party, and `PRIVACY.md` opens with "This product
is used by children. That is the reason for every decision below." The
eligibility flow keeps a minor's answers on the device. The retention job logs
counts and never what anybody asked. Turning on a tracer that uploads every
prompt and every reply would quietly undo all of that.

So tracing here is three decisions rather than one flag:

    LANGSMITH_TRACING=false     off, and off is the default
    LANGSMITH_TRACING=true      the SHAPE of the turn is uploaded: which agents
                                ran, in what order, how long each took, what
                                errored -- with inputs and outputs redacted by
                                the SDK before they leave this process
    LANGSMITH_TRACE_CONTENT=true    additionally uploads the words. A separate
                                variable because it is a separate decision,
                                with a separate owner, and it should not be
                                reachable by pasting one line from a tutorial.

The redacted mode is not a consolation prize. Every question the run sheet
asked -- did the lesson swallow a game request, did the story reach the model
at all, which agent answered a seventeen-year-old, how long did retrieval take
-- is answered by the trajectory and the metadata below, none of which is
anything a child typed.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

#: Facts about a turn that are worth grouping traces by and are nobody's
#: personal data: which voice, which band, which language, which agent. A
#: session id is here because a trace nobody can tie to the next trace is a
#: much weaker tool -- and it is already an opaque server-minted value, not a
#: name, an email or a device.
_METADATA_KEYS: tuple[str, ...] = (
    "persona",
    "age_band",
    "locale",
    "account_status",
    "active_agent",
    "overlay",
)


@lru_cache(maxsize=1)
def _client() -> Any | None:
    """The LangSmith client, built once, with redaction decided here.

    `hide_inputs` and `hide_outputs` are constructor arguments and have no
    environment variable, which is the whole reason this function exists rather
    than a line in a deployment script: the safe default has to be chosen in
    code, by somebody who has read the privacy policy.
    """
    from app.config import get_settings

    settings = get_settings()
    if not settings.langsmith_tracing:
        return None
    if not settings.langsmith_api_key:
        logger.warning(
            "LANGSMITH_TRACING is on but LANGSMITH_API_KEY is not set; "
            "tracing stays off. Nothing is uploaded and nothing breaks."
        )
        return None

    from langsmith import Client

    redact = not settings.langsmith_trace_content
    if not redact:
        logger.warning(
            "LANGSMITH_TRACE_CONTENT is on: prompts and replies WILL be "
            "uploaded to LangSmith. This product is used by children -- see "
            "PRIVACY.md before leaving this on."
        )
    return Client(
        api_key=settings.langsmith_api_key,
        hide_inputs=redact,
        hide_outputs=redact,
    )


def tracing_enabled() -> bool:
    """Whether this process will send anything to LangSmith."""
    return _client() is not None


def configure() -> None:
    """Called once at startup. Says out loud what it decided."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.langsmith_tracing:
        logger.info("LangSmith tracing is off.")
        return
    if _client() is None:
        return
    # The SDK reads this for the default project when a tracer does not name one.
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    logger.info(
        "LangSmith tracing on, project=%s, content=%s.",
        settings.langsmith_project,
        "UPLOADED" if settings.langsmith_trace_content else "redacted",
    )


def turn_config(
    config: dict[str, Any], state: dict[str, Any], *, session_id: str = ""
) -> dict[str, Any]:
    """The graph config, with a tracer and this turn's labels attached.

    Returns `config` untouched when tracing is off, which is the common case and
    must cost nothing: no client, no import, no callback, no allocation beyond
    the check.
    """
    client = _client()
    if client is None:
        return config

    from app.config import get_settings
    from langchain_core.tracers import LangChainTracer

    settings = get_settings()
    metadata = {key: str(state.get(key) or "") for key in _METADATA_KEYS}
    if session_id:
        metadata["session_id"] = session_id

    tags = [f"persona:{metadata.get('persona') or 'unknown'}",
            f"band:{metadata.get('age_band') or 'unknown'}",
            f"locale:{metadata.get('locale') or 'en'}"]

    traced = dict(config)
    traced["callbacks"] = [
        *(config.get("callbacks") or []),
        LangChainTracer(project_name=settings.langsmith_project, client=client),
    ]
    traced["metadata"] = {**(config.get("metadata") or {}), **metadata}
    traced["tags"] = [*(config.get("tags") or []), *tags]
    traced["run_name"] = "aspire.turn"
    return traced
