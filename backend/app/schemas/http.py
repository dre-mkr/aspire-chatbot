"""Pydantic request/response models for the HTTP API."""

from pydantic import BaseModel, Field


class Source(BaseModel):
    """One knowledge-base snippet the agent actually retrieved for this turn.

    NOT the live contract. Nothing constructs a `ChatResponse`: the only chat
    route is `POST /v2/chat/stream`, and a turn's sources reach the client as a
    `CitationsDirective` (`app/schemas/directives.py`) carrying one `CitationRef`
    per cited row -- kb_id, the row's question and snippet, and its validated
    `url`/`site`/`page`/`domain`. Anything reviving this model must carry those
    fields too, or it will serve sources with nothing to open.
    """

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
    # How many teaching concepts the tutor can actually resolve.
    #
    # Zero is a broken deployment that looks exactly like a working one from
    # every other signal. With an empty store the tutor cannot claim a turn, so
    # "explain budgeting to me" stops being a topic to teach and becomes
    # whatever mastery-based placement picks -- the reader gets a check question
    # about a concept they did not ask about, identically, every time.
    #
    # `seed_curriculum` runs at startup and `ConceptStore.reload` swallows its
    # own failure, so nothing said. Now something does, from outside, over curl.
    concepts: int = 0

    #: Concepts the tutor can actually TEACH, per band.
    #:
    #: `concepts` above counts rows, which is a weaker thing than its comment
    #: claims. A row is loaded when its status is servable; it is teachable only
    #: when it also has a BODY for the band in front of it -- `teachable_at`
    #: ends on `body_for(band) is not None`. The two numbers come apart exactly
    #: when the concepts table holds metadata shells: `seed_curriculum` writes
    #: eight columns and none of them is a body, so a deployment seeded only by
    #: it reports a healthy count and cannot teach a single thing.
    #:
    #: That is the failure this endpoint was added to catch, and until now it
    #: reported the number that does not catch it.
    concepts_teachable: dict[str, int] = Field(default_factory=dict)

    #: Concepts carrying at least one authored check question.
    #:
    #: Separate from teachability because they fail separately: a concept can
    #: have a body to teach from and no check to ask, in which case the tutor
    #: explains and never verifies.
    concepts_with_checks: int = 0

    #: Whether semantic resolution is available at all.
    #:
    #: Without embeddings there is no matrix to rank against, so "explain
    #: budgeting to me" cannot be matched to a concept by meaning -- which is
    #: the only way an unnamed topic ever reaches the tutor.
    concepts_ranked: bool = False

