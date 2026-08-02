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

    # Which language the conversation is being held in, from the client's
    # existing language setting -- the same one the title call already sends.
    #
    # It is not optional as far as the response cache is concerned: it is part
    # of the cache key, because serving a cached English answer into a Spanish
    # session is a silent, plausible-looking, wrong answer. Defaulting to "en"
    # means an older client that omits it keeps its own English answers and can
    # never be handed someone else's.
    language: str = Field(default="en", max_length=8)

    # Whether this caller is a full account holder, and whatever else the
    # routing layer distinguishes. Unset means unknown, matching `persona`.
    # Carried so it can key the cache and filter retrieval; nothing here decides
    # anything from it.
    account_status: str | None = Field(default=None, max_length=32)


class Source(BaseModel):
    """One knowledge-base snippet the agent actually retrieved for this turn."""

    content: str
    metadata: dict = Field(default_factory=dict)


class StartedGame(BaseModel):
    """What the client needs to render a game that has just begun.

    A closed model rather than a free dict, and that is load-bearing: this rides
    on the chat response, and `tests/games/test_no_answer_leak.py` exists to
    prove that response has no field an answer could travel in. A dict would be
    exactly such a field -- it would satisfy nothing and could carry anything.

    Every field here is already visible to the player: which game, what it is
    called, whether items are scrambles or statements, and how many there are.
    There is deliberately no room for the item text or its solution.
    """

    game_type: str
    display_name: str
    kind: str
    total: int


class StartedEligibilityCheck(BaseModel):
    """Set when this turn opened the eligibility card.

    Deliberately almost empty, and that is the design. The card fetches its own
    question from `/api/eligibility/state`, so nothing about the flow needs to
    ride on the chat response -- and because nothing does, there is no field
    here that a person's answers could ever travel in. `language` is the one
    thing the client cannot re-derive, since a running flow answers in the
    language it was started in.
    """

    check: str
    language: str = "en"


class ChatResponse(BaseModel):
    reply: str
    thread_id: str
    sources: list[Source] = Field(default_factory=list)
    # Two suggested next questions, grounded in what was just discussed. Best
    # effort: an empty list simply means the client shows no suggestions.
    follow_ups: list[str] = Field(default_factory=list)

    # Set when this turn started a game, and `reply` is then deliberately empty:
    # the card the client renders IS the turn, and anything the model said
    # beside it would put the same puzzle on screen twice.
    #
    # Carries what the client needs without a second round trip -- which game,
    # and how many items -- so the card can appear in the same commit as the
    # message rather than a poll later.
    game_started: StartedGame | None = None

    # Set when this turn opened the eligibility card. `reply` is empty for the
    # same reason it is on a game turn: the card is the whole of the turn, and
    # prose beside it would be a second, unaudited answer to the question the
    # card is about to answer properly.
    eligibility_started: StartedEligibilityCheck | None = None


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
    # Whether the data layer is actually wired up, so a deployment that fell
    # back to in-process memory is visible rather than merely slower.
    database: bool = False
    cache: bool = False
    # Hits, misses and the rate, counted in Valkey rather than in process so the
    # number survives a restart and means something over a day of use.
    cache_stats: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    detail: str
