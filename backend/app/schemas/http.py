"""Pydantic request/response models for the HTTP API."""

from pydantic import BaseModel, Field


class Source(BaseModel):
    """One knowledge-base snippet the agent actually retrieved for this turn."""

    content: str
    metadata: dict = Field(default_factory=dict)


class StartedGame(BaseModel):
    """What the client needs to render a game that has just begun."""

    game_type: str
    display_name: str
    kind: str
    total: int


class StartedEligibilityCheck(BaseModel):
    """Set when this turn opened the eligibility card."""

    check: str
    language: str = "en"


class ChatResponse(BaseModel):
    reply: str
    thread_id: str
    sources: list[Source] = Field(default_factory=list)
    # Two suggested next questions, grounded in what was just discussed.
    follow_ups: list[str] = Field(default_factory=list)

    # Set when this turn started a game, and `reply` is then deliberately empty.
    game_started: StartedGame | None = None

    # Set when this turn opened the eligibility card.
    eligibility_started: StartedEligibilityCheck | None = None


class TitleRequest(BaseModel):
    """Names one conversation, once, from its opening exchange."""

    message: str = Field(min_length=1, max_length=8000)
    answer: str = Field(min_length=1, max_length=20000)
    # Which language to write the title in.
    language: str = Field(default="en", max_length=8)


class TitleResponse(BaseModel):
    # Null when the opening message carried no real subject, or when the call failed.
    title: str | None = None


class HealthResponse(BaseModel):
    status: str
    # Whether the data layer is wired up, so a fallback to in-process memory is visible.
    database: bool = False
    cache: bool = False
    # Hits, misses and the rate, counted in Valkey so the numbers survive a restart.
    cache_stats: dict = Field(default_factory=dict)

