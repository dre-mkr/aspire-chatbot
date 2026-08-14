"""Application configuration, loaded from environment / .env via pydantic-settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root is the directory containing `app/`.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env into os.environ as well as into Settings below.
load_dotenv(BASE_DIR / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Sessions ---
    # HMAC key for session tokens.
    session_secret: str = ""

    # How many anonymous sessions one address may create per hour.
    anonymous_sessions_per_ip_per_hour: int = 30

    # How long an anonymous conversation is kept before deletion.
    anonymous_retention_days: int = 180

    # Where the browser reaches this product.
    public_web_url: str = "http://localhost:3000"

    # Mail.
    resend_api_key: str = ""
    mail_from: str = "ASPIRE <no-reply@aspire.kn>"
    # Whether the console provider may write message bodies to the log.
    mail_console_logs_links: bool = False

    # --- Chat model ---
    # Passed straight to init_chat_model, so it must be in "provider:model" form.
    chat_model: str = "openai:gpt-5.6-luna"

    # Left unset by default, which means "don't send a temperature at all".
    chat_temperature: float | None = None

    # --- Per-persona model routing ---
    # Persona name -> "provider:model" override; anything unlisted falls back to chat_model.
    chat_model_by_persona: dict[str, str] = {}

    # Persona name -> max output tokens, with "" as the key for the no-persona case.
    max_tokens_by_persona: dict[str, int] = {}

    # OpenAI only, required for GPT-5: those models reject function tools on /v1/chat/completions.
    openai_use_responses_api: bool = True

    # Read by the provider SDK. Only the key matching `chat_model` needs a value.
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # --- Embeddings ---
    # Configured separately from the chat model.
    embeddings_provider: Literal["openai", "fastembed"] = "openai"
    # 3072 dims.
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
    #: Minimum similarity for a chunk to reach the prompt.
    retriever_score_threshold: float = Field(default=0.2, ge=0.0, le=1.0)

    #: Generate follow-up chips on every turn, not just the opening one.
    follow_ups_always: bool = True

    # --- Postgres (Neon) ---
    # MUST be the POOLED endpoint, not the direct host.
    database_url: str | None = None
    # Neon scales to zero, so the first request after an idle period pays the wake-up.
    database_warm_on_start: bool = True
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)

    # --- Valkey ---
    # Wire-compatible with Redis 7.2, so a redis client speaks to it unchanged.
    valkey_url: str | None = None
    # How long a cached answer stays servable.
    response_cache_ttl_seconds: int = Field(default=6 * 3600, ge=60, le=1_209_600)
    response_cache_enabled: bool = True

    # --- Semantic response cache (layer 2) ---
    # On a layer-1 miss, a query whose embedding is near a cached one reuses that answer.
    semantic_cache_enabled: bool = False
    semantic_cache_threshold: float = Field(default=0.95, ge=0.80, le=1.0)
    # How many cached-query embeddings one (persona, language, status) shelf holds.
    semantic_cache_max_entries: int = Field(default=512, ge=8, le=4096)

    # --- Query-embedding cache ---
    # Embedding a query is a ~400 ms network round trip, so the vector is cached.
    embedding_cache_enabled: bool = True
    embedding_cache_ttl_seconds: int = Field(default=30 * 86_400, ge=3600, le=90 * 86_400)

    # --- LangGraph platform ---
    # The checkpointer keeps its own psycopg pool, sized separately from the app's.
    checkpointer_pool_size: int = Field(default=4, ge=1, le=20)
    checkpointer_connect_timeout: float = Field(default=30.0, ge=1.0, le=120.0)
    #: How long a pooled connection may live before the pool replaces it.
    checkpointer_max_lifetime: float = Field(default=180.0, ge=30.0, le=3600.0)

    # `GRAPH_ENABLED` used to live here.

    # The classifier and the widget planner.
    classifier_model: str = "openai:gpt-4o"
    classifier_temperature: float = 0.0
    #: Below this a differing classification does NOT displace a sticky agent.
    classifier_stickiness_threshold: float = Field(default=0.75, ge=0.0, le=1.0)

    # Retrieval for the QA subgraph.
    qa_retrieve_k: int = Field(default=12, ge=1, le=50)
    qa_rerank_k: int = Field(default=4, ge=1, le=20)
    #: RRF's smoothing constant.
    qa_rrf_k: int = Field(default=60, ge=1, le=200)
    #: The QA relevance floor, as a COSINE similarity from the dense retriever.
    qa_relevance_floor: float = Field(default=0.55, ge=0.0, le=1.0)
    #: Below this, retrieval found nothing and no citation rescues the answer.
    #: Between this and `qa_relevance_floor` the score is marginal, and whether
    #: the answer cites a retrieved extract decides. See `qa/nodes.ground_check`.
    qa_relevance_hard_floor: float = Field(default=0.35, ge=0.0, le=1.0)

    #: Lexical fallback floor: the share of the question's content words that were retrieved.
    qa_coverage_floor: float = Field(default=0.25, ge=0.0, le=1.0)

    # --- The learning agent ---
    # Model tiering in one place: each job below names the model its difficulty earns.

    #: Disambiguates between two or three candidate concepts.
    learn_resolve_model: str = "openai:gpt-4o"
    #: Picks one widget primitive from a short list, or none.
    learn_widget_plan_model: str = "openai:gpt-4o"
    #: Composes the primitive's JSON on gpt-4o; gpt-5.6-luna took ~5.4s and missed the 3.5s budget.
    learn_widget_compose_model: str = "openai:gpt-4o"

    # Concept resolution thresholds, configurable because they are decision boundaries worth tuning.

    #: At or above this cosine similarity, the concept is resolved outright.
    learn_resolve_threshold: float = Field(default=0.62, ge=0.0, le=1.0)
    #: Between the two thresholds, one cheap structured call picks among the top candidates.
    learn_disambiguate_floor: float = Field(default=0.45, ge=0.0, le=1.0)
    #: How many candidates the disambiguation call is shown.
    learn_disambiguate_k: int = Field(default=3, ge=2, le=5)

    # How long the widget task may run after the prose has settled, keeping the two independent.
    learn_widget_timeout_s: float = Field(default=3.5, gt=0.0, le=30.0)
    #: A validated widget config is reused for this long.
    learn_widget_cache_ttl_days: int = Field(default=7, ge=1, le=90)

    # Widgets.
    widgets_enabled: bool = True
    #: A candidate widget is not regenerated for this long, even on a miss.
    widget_candidate_ttl_days: int = Field(default=30, ge=1, le=365)
    #: Hard ceiling on a buffered sentinel before it is discarded.
    widget_buffer_limit_bytes: int = Field(default=4096, ge=512, le=65536)

    # Object storage for registration documents.
    s3_endpoint_url: str | None = None
    s3_bucket: str = "aspire-documents"
    s3_region: str = "us-east-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    #: How long an upload or download URL stays valid.
    s3_url_ttl_seconds: int = Field(default=900, ge=60, le=3600)

    # The vision model that looks at an uploaded document.
    doc_check_model: str = ""

    # Encryption key for `application_pii`, base64-encoded 32 bytes (Fernet).
    pii_encryption_key: str | None = None

    # --- Conversation memory ---
    # On by default; the summarisation it drives runs after the answer has gone out.
    memory_window_enabled: bool = True
    # How many recent messages the model sees verbatim.
    memory_window_turns: int = Field(default=6, ge=1, le=50)
    # Summarise once this many messages have fallen outside the window.
    memory_summary_after_turns: int = Field(default=2, ge=1, le=50)
    # Used only for accounting. o200k_base is the GPT-4o/5 family's encoding.
    token_encoding: str = "o200k_base"

    # --- Rate limits on the endpoints that spend model calls ---
    # Counted per proven identity where there is one, and per address otherwise.
    # --- ASPIRE's own contact details ---
    #
    # The prompt has always told the model to offer these and never to invent
    # one, and never supplied any -- so a decline ended with no way to reach a
    # person. The defaults below are the values the corpus already publishes
    # (ASP-208, ASP-209, ASP-211, ASP-299/300) and which
    # `eligibility/content.py` already hardcodes; they are sourced, not
    # invented. CONFIRM THEM WITH THE CLIENT before the 20th: a stale number on
    # a government service is a visible error.
    aspire_contact_email: str = "aspire@gov.kn"
    aspire_contact_phone: str = "+1 (869) 667-5566"
    aspire_contact_website: str = "aspire.gov.kn"
    aspire_contact_office: str = "The Cable Office, Cayon Street, Basseterre (Mon-Fri, 9:00 AM - 3:00 PM)"

    chat_rate_window_seconds: int = Field(default=600, ge=10, le=3600)
    chat_messages_per_window: int = Field(default=30, ge=1, le=1000)
    #: How many graph sessions one address may mint per window. `/v2/session`
    #: had no limit of any kind, and it is the supply of tokens for everything
    #: downstream that does. Generous on purpose: a real reader mints one per
    #: conversation per page load, so this only bites a script.
    graph_sessions_per_window: int = Field(default=120, ge=1, le=10_000)
    # Titles are one per conversation, so this only has to allow starting a lot of chats.
    title_requests_per_window: int = Field(default=20, ge=1, le=1000)

    # --- HTTP ---
    # Origins allowed to call this API from a browser.
    cors_allow_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    log_level: str = "INFO"

    def resolved(self, path: Path) -> Path:
        """Make a possibly-relative configured path absolute against the project root."""
        return path if path.is_absolute() else (BASE_DIR / path)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor so settings are parsed once per process."""
    return Settings()
