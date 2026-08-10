"""Pydantic request/response models for the HTTP API."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    # Omit or send null on the first turn; the response carries the id to reuse.
    thread_id: str | None = None
    # Drives the client's "Explain it simply" toggle: asks for plainer language without changing the facts.
    simple_mode: bool = False
    # Who is talking: "stella", "orion", "aurora" or "nova".
    persona: str | None = Field(default=None, max_length=32)

    # Which language the conversation is being held in, from the client's existing language setting -- the same one…
    language: str = Field(default="en", max_length=8)

    # Whether this caller is a full account holder, and whatever else the routing layer distinguishes.
    account_status: str | None = Field(default=None, max_length=32)


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

    # Set when this turn started a game, and `reply` is then deliberately empty: the card the client renders IS the…
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
    # Whether the data layer is actually wired up, so a deployment that fell back to in-process memory is visible r…
    database: bool = False
    cache: bool = False
    # Hits, misses and the rate, counted in Valkey rather than in process so the number survives a restart and mean…
    cache_stats: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    detail: str
