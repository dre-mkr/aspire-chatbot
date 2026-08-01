"""Pydantic request/response models for the HTTP API."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    # Omit or send null on the first turn; the response carries the id to reuse.
    thread_id: str | None = None
    # Drives the client's "Explain it simply" toggle: asks for plainer language
    # without changing the facts. Both modes share one conversation thread.
    simple_mode: bool = False
    # Who is talking: "stella", "orion", "aurora" or "nova". Optional because no
    # client selects one yet.
    #
    # Left unset it means "we do not know", which is deliberately NOT the same as
    # any particular persona: features that vary by audience treat unknown as
    # permissive. Games, for instance, are for account holders and decline an
    # explicit "aurora", but an unknown caller is allowed to play rather than
    # silently locked out of the feature.
    #
    # Kept as a plain string rather than an enum so the chat API stays
    # independent of the voice and games modules, either of which can be off.
    # Consumers parse it and ignore anything they do not recognise.
    persona: str | None = Field(default=None, max_length=32)


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


class TitleRequest(BaseModel):
    """Names one conversation, once, from its opening exchange."""

    message: str = Field(min_length=1, max_length=8000)
    answer: str = Field(min_length=1, max_length=20000)
    # Which language to write the title in. Comes from the client's existing
    # voice/language setting rather than being detected here, so the title
    # agrees with the rest of the interface. Unrecognised values mean English.
    language: str = Field(default="en", max_length=8)


class TitleResponse(BaseModel):
    # Null when the opening message carried no real subject, or when the call
    # failed. Either way the client keeps its own fallback -- this endpoint
    # never invents a title and never returns an error the user would see.
    title: str | None = None


class HealthResponse(BaseModel):
    status: str


class ErrorResponse(BaseModel):
    detail: str
