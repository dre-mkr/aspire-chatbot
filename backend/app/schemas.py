"""Pydantic request/response models for the HTTP API."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    # Omit or send null on the first turn; the response carries the id to reuse.
    thread_id: str | None = None
    # Drives the client's "Explain it simply" toggle: asks for plainer language
    # without changing the facts. Both modes share one conversation thread.
    simple_mode: bool = False


class Source(BaseModel):
    """One knowledge-base snippet the agent actually retrieved for this turn."""

    content: str
    metadata: dict = Field(default_factory=dict)


class ChatResponse(BaseModel):
    reply: str
    thread_id: str
    sources: list[Source] = Field(default_factory=list)
    # Two suggested next questions, grounded in what was just discussed. Best
    # effort: an empty list simply means the client shows no suggestions.
    follow_ups: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str


class ErrorResponse(BaseModel):
    detail: str
