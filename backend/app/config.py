"""Application configuration, loaded from environment / .env via pydantic-settings.

Every tunable knob lives here so nothing else in the codebase reads os.environ
or hardcodes a path, model name, or key.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root is the directory containing `app/`. Relative paths in settings are
# resolved against this rather than the process CWD, so `uvicorn app.main:app` and
# `python -m app.ingest` agree on where ./data lives no matter where they're run from.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env into os.environ as well as into Settings below.
# Both are needed, and for different reasons: Settings gives us typed, validated
# config, while the provider SDKs (openai, anthropic) read their credentials
# straight from os.environ and never see the Settings object. Without this, a key
# present in .env is parsed correctly and still never reaches the SDK.
# override=False so a real environment variable beats the .env file.
load_dotenv(BASE_DIR / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Sessions ---------------------------------------------------------
    # HMAC key for session tokens. No default on purpose: a signing key with a
    # fallback value is a signing key an attacker also has, and the failure mode
    # of forgetting to set it must be a refusal at boot rather than forged
    # sessions in production.
    session_secret: str = ""

    # How many anonymous sessions one address may create per hour. Anonymous
    # access removes the usual lever -- there is no address to ban -- so the
    # limit is the lever. Generous enough for a shared school connection,
    # tight enough that scripting a thousand identities is noticed.
    anonymous_sessions_per_ip_per_hour: int = 30

    # How long an anonymous conversation is kept before deletion. Documented in
    # PRIVACY.md; enforced by the retention job.
    anonymous_retention_days: int = 180

    # Where the browser reaches this product. Used to build the links in reset
    # and sign-in emails, so it must be the address a person can actually open.
    public_web_url: str = "http://localhost:3000"

    # Mail. Unset means the console provider: links are written to the log,
    # which keeps development and the test suite off the network entirely.
    resend_api_key: str = ""
    mail_from: str = "ASPIRE <no-reply@aspire.kn>"

    # --- Chat model -------------------------------------------------------
    # Passed straight to init_chat_model, so the "provider:model" form selects
    # the provider. Swap to "anthropic:claude-sonnet-4-6" etc. without touching code.
    # Note: "openai:gpt-5.6" is an alias that routes to Sol, so name Luna explicitly.
    chat_model: str = "openai:gpt-5.6-luna"

    # Left unset by default, which means "don't send a temperature at all".
    # The GPT-5 family rejects any value other than its default and errors on the
    # request, so this must stay None for those models. Set it only for a model
    # you know accepts it (e.g. Claude, gpt-4o).
    chat_temperature: float | None = None

    # OpenAI only, and required for the GPT-5 family: on /v1/chat/completions those
    # models reject function tools whenever reasoning is active, which breaks the
    # retriever tool. Routing through /v1/responses instead keeps tool calling and
    # reasoning working together. (The alternative, reasoning_effort="none", also
    # works but turns reasoning off.) Ignored for non-OpenAI providers.
    openai_use_responses_api: bool = True

    # Read by the provider SDK. Only the key matching `chat_model` needs a value.
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # --- Embeddings -------------------------------------------------------
    # Configured separately from the chat model (embeddings are their own API).
    # "fastembed" runs locally with no key and no per-token cost -- useful for
    # offline work -- but "openai" is the default here.
    # `rag.build_embeddings` is the single place that reads these.
    #
    # Changing either value changes the vector dimensions, which makes any
    # existing Chroma store unreadable. Delete data/chroma and re-ingest after
    # touching these.
    embeddings_provider: Literal["openai", "fastembed"] = "openai"
    # 3072 dims. Note that access to embedding models is per-project: not every
    # OpenAI project can use every model, and an unavailable one fails with a 403
    # "does not have access to model" at ingest time.
    embeddings_model: str = "text-embedding-3-large"

    # --- Vector store -----------------------------------------------------
    chroma_dir: Path = BASE_DIR / "data" / "chroma"
    chroma_collection: str = "aspire_knowledge_base"

    # --- Knowledge base ingestion ----------------------------------------
    knowledge_base_csv: Path = BASE_DIR / "data" / "knowledge_base.csv"
    # Rows are usually short enough to stay whole; only longer ones get split.
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # --- Retrieval --------------------------------------------------------
    retriever_k: int = Field(default=4, ge=1, le=20)

    # --- Postgres (Neon) --------------------------------------------------
    # MUST be the POOLED endpoint -- the host with `-pooler` in it. Neon's
    # direct endpoint holds one Postgres backend per connection and a
    # per-request async session pool will exhaust it; the pooled host
    # multiplexes through pgbouncer. `db/engine.py` warns at startup if this
    # does not look pooled.
    #
    # Unset means "no database", which is a fully supported state: at this step
    # nothing in the request path reads Postgres at all, so leaving it unset
    # changes nothing whatsoever.
    database_url: str | None = None
    # Neon scales to zero, so the first request after an idle period pays the
    # wake-up. Warming one connection at startup costs nothing and keeps the
    # overnight compute bill at zero, which disabling scale-to-zero would not.
    database_warm_on_start: bool = True
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)

    # --- Valkey -----------------------------------------------------------
    # Wire-compatible with Redis 7.2, so redis-py and arq talk to it unchanged.
    # Unset disables the response cache and the background queue; nothing else
    # changes.
    valkey_url: str | None = None
    # How long a cached answer stays servable. Knowledge-base answers are stable
    # for far longer than this, but a few hours is the point past which a
    # corrected answer should have reached everyone.
    response_cache_ttl_seconds: int = Field(default=6 * 3600, ge=60, le=86_400)
    response_cache_enabled: bool = True

    # --- Conversation memory ---------------------------------------------
    # OFF by default. Enabling this changes what the model sees: the last N
    # turns verbatim plus a running summary of everything older, instead of the
    # whole thread. Flip it back and today's behaviour returns exactly, because
    # the full transcript is persisted either way.
    memory_window_enabled: bool = False
    # How many recent messages the model sees verbatim. The single number that
    # decides the per-turn prompt cost, which is why it is configurable.
    memory_window_turns: int = Field(default=6, ge=1, le=50)
    # Summarise once this many messages have fallen outside the window. Runs in
    # arq, off the request path, always.
    memory_summary_after_turns: int = Field(default=2, ge=1, le=50)
    # Used only for accounting. o200k_base is the GPT-4o/5 family's encoding.
    token_encoding: str = "o200k_base"

    # --- HTTP -------------------------------------------------------------
    # Permissive for local dev. Tighten to the real frontend origin before deploying.
    cors_allow_origins: list[str] = ["*"]
    log_level: str = "INFO"

    def resolved(self, path: Path) -> Path:
        """Make a possibly-relative configured path absolute against the project root."""
        return path if path.is_absolute() else (BASE_DIR / path)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor so settings are parsed once per process."""
    return Settings()
