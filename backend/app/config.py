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
