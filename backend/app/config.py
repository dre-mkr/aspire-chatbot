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

    # --- Per-persona model routing (P14-A) --------------------------------
    # Persona name -> "provider:model" override. Any persona not in the dict --
    # and the no-persona case -- uses `chat_model`. A dict rather than four
    # fields so it can be tuned from the environment without a code change:
    #
    #   CHAT_MODEL_BY_PERSONA={"stella": "openai:gpt-5.6-halley"}
    #
    # EMPTY BY DEFAULT, DELIBERATELY. Routing a persona to a different model
    # changes the wording of every answer that persona gets, which rule 2 of the
    # latency workstream forbids shipping silently. The mechanism is here so the
    # decision is one config edit -- but the decision needs an eval run in front
    # of it (`python -m evals.run --answers`), not a default.
    chat_model_by_persona: dict[str, str] = {}

    # Persona name -> max output tokens, with "" as the key for the no-persona
    # case. Empty means "no cap", today's behaviour. A cap is a guard against a
    # runaway generation, not a style control: set it comfortably above the
    # longest legitimate answer (measured p99 output on the probe set is ~350
    # tokens) or it will truncate real answers mid-sentence.
    max_tokens_by_persona: dict[str, int] = {}

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
    # How long a cached answer stays servable. The ceiling was one day when the
    # corpus fingerprint was not part of the key; now that it is (P13-006), an
    # edited knowledge base retires its answers by key rotation rather than by
    # expiry, so a long TTL cannot outlive a correction and the cap is raised to
    # accommodate the 7-day setting (P14-B).
    response_cache_ttl_seconds: int = Field(default=6 * 3600, ge=60, le=1_209_600)
    response_cache_enabled: bool = True

    # --- Semantic response cache (P14-B, layer 2) --------------------------
    # On a layer-1 miss, a query whose embedding is close enough to a cached
    # query's -- same persona, language and account status -- is served that
    # cached answer. The embedding is the one the turn computes for retrieval
    # anyway, so a miss costs one Valkey read and a dot product, not a model
    # call.
    #
    # OFF BY DEFAULT, on a measurement rather than a hunch. At the proposed 0.95
    # threshold, `scripts/semantic_margin.py` measured the two populations this
    # gate must separate OVERLAPPING: "Is ASPIRE for children aged 5 to 18?" ~
    # "...aged 5 to 12?" sits at 0.9645 cosine (a wrong eligibility answer for a
    # minor, served confidently), while every genuine paraphrase pair measured
    # BELOW 0.95 (0 of 16 would hit). There is no threshold that is both useful
    # and safe on this embedding model; cosine similarity cannot tell "same
    # question, different words" from "different question, similar words" at
    # the granularity a government FAQ needs. The machinery is complete and this
    # flag is the decision, deliberately left to a human with these numbers.
    semantic_cache_enabled: bool = False
    semantic_cache_threshold: float = Field(default=0.95, ge=0.80, le=1.0)
    # How many cached-query embeddings one (persona, language, status) shelf
    # holds. Oldest out first past the cap: the point is the head of the
    # distribution -- the starter chips and their paraphrases -- not an archive.
    semantic_cache_max_entries: int = Field(default=512, ge=8, le=4096)

    # --- Query-embedding cache (P14-D) -------------------------------------
    # Embedding a query is a ~400 ms network round trip to OpenAI; a repeat of
    # the same normalised text is the same vector every time (modulo provider
    # nondeterminism measured at ~1e-4, far below anything retrieval can
    # distinguish). Keyed on the normalised query and the embedding model name,
    # so a model change can never serve stale vectors.
    embedding_cache_enabled: bool = True
    embedding_cache_ttl_seconds: int = Field(default=30 * 86_400, ge=3600, le=90 * 86_400)

    # --- LangGraph platform (Tracks A-G) ----------------------------------
    # The checkpointer keeps its own psycopg pool, separate from SQLAlchemy's
    # asyncpg one -- see app/graph/checkpointer.py for why the two cannot be
    # shared. Small on purpose: one graph turn holds one connection briefly, and
    # a large pool on a pooled Neon endpoint just consumes pgbouncer client
    # slots that the request path has better uses for.
    checkpointer_pool_size: int = Field(default=4, ge=1, le=20)
    checkpointer_connect_timeout: float = Field(default=30.0, ge=1.0, le=120.0)
    #: How long a pooled connection may live before the pool replaces it. Well
    #: under Neon's idle window on purpose -- a serverless endpoint hangs up on
    #: quiet connections, and the pool cannot be told about a hangup it did not
    #: perform. See `get_checkpointer`, which also verifies on checkout; this
    #: setting is what keeps that verification from being the common path.
    #:
    #: This is the psycopg spelling of what `db/engine.py` already does for the
    #: request path with `pool_recycle=280` and `pool_pre_ping=True`. The two
    #: pools face the same endpoint and needed the same defence; only the request
    #: path had it, which is why a turn could fail on reading its own thread back
    #: while every query around it succeeded.
    checkpointer_max_lifetime: float = Field(default=180.0, ge=30.0, le=3600.0)

    # `GRAPH_ENABLED` used to live here. It is gone rather than defaulted to
    # true: it guarded whether /v2 was mounted at all, and now that /v2 is the
    # only chat path, a flag that can unmount it is not a safety control but an
    # outage one environment file away.
    #
    # The eval gate it was meant to enforce is `make eval`, which fails CI on a
    # threshold -- a check that runs, rather than a switch somebody remembers.

    # The classifier and the widget planner. Small and old, deliberately:
    # routing between six names and picking one of nine primitives are both
    # short-context classification jobs, and spending a frontier model on them
    # would put a second expensive call in front of every turn.
    #
    # gpt-4o rather than a GPT-5-family model for one concrete reason:
    # `classifier_temperature` below is 0.0 and routing wants it. The GPT-5
    # family accepts only its own default temperature, so `build_classifier_model`
    # has to omit the parameter for those models -- and a router that cannot be
    # pinned to 0 is a router that can send the same message two ways.
    #
    # gpt-4o rather than gpt-4o-mini only because access to OpenAI models is
    # granted per project and the mini variants are not on this one; a project
    # that has them should prefer mini here. An unavailable model does not fail
    # loudly -- `classify` catches the 403 and falls back -- so check
    # `client.models.list()` before naming one.
    #
    # Configured separately from `chat_model` so the two can move independently
    # -- swapping the answer model must not silently re-tune the router.
    classifier_model: str = "openai:gpt-4o"
    classifier_temperature: float = 0.0
    #: Below this a differing classification does NOT displace a sticky agent.
    #: Mid-registration and mid-lesson conversations must survive an ambiguous
    #: turn; see `nodes/classify.py`.
    classifier_stickiness_threshold: float = Field(default=0.75, ge=0.0, le=1.0)

    # Retrieval for the QA subgraph. Hybrid because the corpus is 338 rows: at
    # that size a dense-only search misses exact-term queries ("ASP-042", "EC$",
    # a school name) that BM25 finds trivially.
    qa_retrieve_k: int = Field(default=12, ge=1, le=50)
    qa_rerank_k: int = Field(default=4, ge=1, le=20)
    #: RRF's smoothing constant. 60 is the value from the original paper and
    #: there is no reason to differ without measurement.
    qa_rrf_k: int = Field(default=60, ge=1, le=200)
    #: The QA relevance floor, as a COSINE similarity from the dense retriever.
    #:
    #: 0.55, and set from a measurement rather than a hunch. On the 706-row
    #: corpus with bge-small, `evals/harness.py` measured the two populations
    #: this would have to separate as OVERLAPPING: in-KB questions run
    #: 0.614-0.873 and out-of-KB questions run 0.443-0.757, so the best possible
    #: threshold still misclassifies 11 of 50. There is no value that is both
    #: useful and safe.
    #:
    #: So this is NOT the discriminator. It is a floor against the absurd --
    #: below it, nothing in the corpus is even the same subject -- and it sits
    #: under the lowest real question (0.614) so it starves nothing. What
    #: actually decides groundedness is ATTRIBUTION: an answer must cite a
    #: retrieved row, and every figure in it must appear in one. See
    #: `agents/qa/nodes.ground_check`.
    qa_relevance_floor: float = Field(default=0.55, ge=0.0, le=1.0)

    #: The lexical fallback floor, as a fraction of the question's own content
    #: words appearing in what was retrieved.
    #:
    #: Only consulted when the dense retriever returned nothing -- a BM25-only
    #: turn. Rank fusion cannot answer "is anything here about this?", because
    #: every chunk a retriever returns ranks highly; word coverage can.
    qa_coverage_floor: float = Field(default=0.25, ge=0.0, le=1.0)

    # Widgets.
    widgets_enabled: bool = True
    #: A candidate widget is not regenerated for this long, even on a miss. The
    #: review queue is a human queue and it does not run daily.
    widget_candidate_ttl_days: int = Field(default=30, ge=1, le=365)
    #: Hard ceiling on a buffered sentinel before it is discarded. A model that
    #: opens a widget block and never closes it must not be able to hold the
    #: whole reply hostage.
    widget_buffer_limit_bytes: int = Field(default=4096, ge=512, le=65536)

    # Object storage for registration documents. Bytes go browser-to-bucket via
    # a presigned URL and never through FastAPI; see app/storage/presign.py.
    s3_endpoint_url: str | None = None
    s3_bucket: str = "aspire-documents"
    s3_region: str = "us-east-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    #: How long an upload or download URL stays valid. Minutes, not hours: a
    #: leaked URL is a document, and the window is the whole mitigation.
    s3_url_ttl_seconds: int = Field(default=900, ge=60, le=3600)

    # The vision model that looks at an uploaded document. ADVISORY ONLY -- it
    # never rejects an application and never blocks a submission (see
    # `agents/register/nodes/doc_check.py`).
    #
    # Empty means no automated opinion at all, which is a fully supported state:
    # every document goes to the human queue exactly as it did before the node
    # existed. That is what makes turning this on a safe change rather than a
    # leap of faith.
    doc_check_model: str = ""

    # Encryption key for `application_pii`, base64-encoded 32 bytes (Fernet).
    # Unset means registration refuses to persist a slot rather than writing a
    # national ID in plaintext.
    pii_encryption_key: str | None = None

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
    # With it on, the thread is compressed instead: the checkpoint keeps recent
    # messages verbatim and folds everything older into a running summary. Cost
    # becomes linear and the process stops accumulating conversations it will
    # never serve again.
    #
    # WHERE THAT WORK HAPPENS MOVED. It used to be the arq summary job, writing
    # `conversations.summary` for `load_context` to read back. The graph reads
    # `state["summary"]` out of its own checkpoint, so `turn.summarise_thread`
    # writes it there instead -- after the stream has closed, where the reader
    # never waits for it. The job was deleted; see `app/jobs.py`.
    #
    # Gated on a database at the point of use (`turn.summarisation_wanted`), so a
    # deployment without Postgres keeps the old behaviour rather than losing its
    # memory: with no checkpointer there is no thread to compress.
    memory_window_enabled: bool = True
    # How many recent messages the model sees verbatim. The single number that
    # decides the per-turn prompt cost, which is why it is configurable.
    #
    # The GRAPH's threshold is `main_graph.SUMMARY_AFTER_MESSAGES`, not this.
    # This one now feeds `build_prompt`, which the token-measurement script uses.
    memory_window_turns: int = Field(default=6, ge=1, le=50)
    # Summarise once this many messages have fallen outside the window.
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
