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
    # Whether the console provider may write message bodies to the log.
    #
    # Those bodies contain working sign-in and password-reset links. Logging them
    # is genuinely useful in development and is how a local password reset is
    # completed at all -- and it is a credential leak anywhere else. OFF by
    # default so the unsafe behaviour has to be asked for rather than inherited
    # by a deploy that forgot RESEND_API_KEY.
    mail_console_logs_links: bool = False

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
    retriever_k: int = Field(default=3, ge=1, le=20)
    #: Minimum similarity for a chunk to reach the prompt. 0 disables the floor.
    #:
    #: Chroma's cosine relevance runs 0..1, higher being closer. 0.2 is
    #: deliberately low: this exists to drop chunks that are plainly unrelated to
    #: the question, not to adjudicate borderline ones. A floor that starves a
    #: real question is a far worse failure than one that lets a weak chunk
    #: through to a system prompt that already refuses correctly 10 times out
    #: of 10. Raise it only with the eval set in front of you.
    retriever_score_threshold: float = Field(default=0.2, ge=0.0, le=1.0)

    #: Generate follow-up chips on every turn, not just the opening one.
    #:
    #: They cost a full model call on EVERY non-card turn -- roughly a 2x
    #: multiplier on per-turn model calls, for a UI affordance whose value is
    #: entirely front-loaded: a reader on turn one does not yet know what to
    #: ask, and by turn twelve they plainly do. The default is the opening turn
    #: only. This exists to restore the old behaviour for anyone who wants to
    #: measure the difference or disagrees with the trade.
    follow_ups_always: bool = True

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
    # ON by default, since the worker that backs it is now actually deployed.
    #
    # With this off, langgraph's InMemorySaver replays the ENTIRE thread into the
    # model every turn -- including every prior turn's ToolMessage carrying its
    # retrieved knowledge-base chunks. Measured: 1,800 tokens of fixed overhead
    # plus 519 of context per turn, so turn n costs roughly
    # 1800 + n x (519 + question + answer). Cost is quadratic in conversation
    # length, and the saver grows without bound in a process that is pinned to a
    # single worker.
    #
    # With it on, history comes from Postgres instead: a window of recent turns
    # plus a running summary of everything older, compressed by the arq worker
    # off the request path. Cost becomes linear and the process stops
    # accumulating conversations it will never serve again.
    #
    # This was off for a good reason until now -- the summarisation job had no
    # worker to run in, so turns falling out of the window were never folded into
    # a summary and would simply have been forgotten. deploy/aspire-worker.service
    # fixes that, which is what makes this flip safe.
    #
    # Gated on a database at the point of use (see `agent.build_agent`), so a
    # deployment without Postgres keeps the old behaviour rather than losing its
    # memory. Flip it back and today's behaviour returns exactly, because the
    # full transcript is persisted either way.
    memory_window_enabled: bool = True
    # How many recent messages the model sees verbatim. The single number that
    # decides the per-turn prompt cost, which is why it is configurable.
    memory_window_turns: int = Field(default=6, ge=1, le=50)
    # Summarise once this many messages have fallen outside the window. Runs in
    # arq, off the request path, always.
    memory_summary_after_turns: int = Field(default=2, ge=1, le=50)
    # Used only for accounting. o200k_base is the GPT-4o/5 family's encoding.
    token_encoding: str = "o200k_base"

    # --- Rate limits on the endpoints that spend model calls ---------------
    # Counted per proven identity where there is one, otherwise per hashed
    # address -- see app/limits.py for why in-process rather than Valkey.
    #
    # Sized for a classroom on one school connection rather than for one child:
    # unauthenticated callers share an address, so the anonymous case is the one
    # these numbers have to survive. Thirty questions in ten minutes is far more
    # than a lesson generates and far less than a script does.
    chat_rate_window_seconds: int = Field(default=600, ge=10, le=3600)
    chat_messages_per_window: int = Field(default=30, ge=1, le=1000)
    # Titles are one per conversation, so this only has to allow starting a lot
    # of chats. It is lower than the message limit on purpose: a title request is
    # a model call with a 28,000-character payload and no conversation behind it.
    title_requests_per_window: int = Field(default=20, ge=1, le=1000)

    # --- HTTP -------------------------------------------------------------
    #: Origins allowed to call this API from a browser.
    #:
    #: The default was `["*"]`, which meant any website could drive `POST /chat`
    #: from a visitor's browser at the programme's model cost. Production is
    #: mitigated by nginx serving app and API on one origin so nothing
    #: preflights, and `allow_credentials` is False so this was abuse exposure
    #: rather than data theft -- but a wildcard default is a wildcard in any
    #: deployment that does not happen to be behind that reverse proxy.
    #:
    #: The default is now the local dev origin, which is the only origin that
    #: legitimately needs a cross-origin grant: the Vite dev server on :3000 is
    #: a different origin from this API on :8000. Production sets
    #: `CORS_ALLOW_ORIGINS=["https://aspire.eccugenai.app"]` explicitly.
    #:
    #: A deployment that genuinely wants the wildcard must now say so, which is
    #: the point.
    cors_allow_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    log_level: str = "INFO"

    def resolved(self, path: Path) -> Path:
        """Make a possibly-relative configured path absolute against the project root."""
        return path if path.is_absolute() else (BASE_DIR / path)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor so settings are parsed once per process."""
    return Settings()
