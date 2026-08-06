"""The single state object every node in the ASPIRE graph reads and writes.

One TypedDict, four regions, and a rule that decides which region a field
belongs in:

  * **Identity** comes from the signed session token and from nothing else. Not
    from the request body, not from a model's inference, not from what a child
    typed. `hydrate` is the only writer and `access.allowed_agents` is the only
    consumer that matters, because on this product "how old is this person" is
    the input to a safety decision rather than a personalisation one.

  * **Conversation** is the transcript plus the routing bookkeeping that decides
    who is answering.

  * **Retrieval** is what the corpus offered this turn, plus how well the answer
    is attributable to it. Empty is a legitimate and important value: an agent
    with no chunks must escalate rather than answer.

  * **Output contract** is what the client is allowed to render. Directives are
    structured and typed rather than parsed out of prose -- see
    `app/schemas/directives.py` for why that boundary is load-bearing.

Agent-local state (`learning`, `registration`) is None whenever that agent is
not active. That is deliberate rather than merely tidy: a registration in
progress must not be visible to, or mutable by, the learning agent, and `None`
is the cheapest possible expression of "this agent is not running".

## On reducers

`messages` uses langgraph's `add_messages`, which is the only reducer whose
semantics are not ours to choose -- it owns message id reconciliation and
partial updates from the streaming layer.

The other two reducers exist because more than one node contributes to the same
list within a single turn, and last-write-wins would silently drop the earlier
contributor's work. Everything else is a plain field: a node that sets it means
to replace it.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from app.schemas.directives import UIDirective

# ── the four closed vocabularies identity is drawn from ──────────────────────
#
# Literal rather than str throughout. These are the values `access.py` switches
# on, and a typo in one of them is not a typo -- it is a child receiving an
# agent their age band excludes. Keeping them as type-level constants means the
# type checker catches the typo and the access matrix never has to guess.

Persona = Literal["stella", "orion", "aurora", "nova"]
AgeBand = Literal["5-8", "9-12", "13-15", "16-18", "adult"]
AccountStatus = Literal["prospect", "applicant", "beneficiary", "guardian"]
Locale = Literal["en", "es", "fr"]

#: Every band, youngest first. Ordered because several rules ("under 16",
#: "13 and up") are comparisons rather than set membership, and comparing by
#: index beats re-deriving the ordering at each call site.
AGE_BANDS: tuple[AgeBand, ...] = ("5-8", "9-12", "13-15", "16-18", "adult")

#: Bands that are legally and editorially children. Named rather than inlined
#: because three separate subsystems -- access, safety_out's link stripping, and
#: the escalation agent's "never route a child off-platform" rule -- ask the
#: same question and must not answer it differently.
MINOR_BANDS: frozenset[str] = frozenset({"5-8", "9-12", "13-15"})


def band_index(band: str) -> int:
    """Where a band sits on the ladder, or -1 if it is not a band we know.

    -1 rather than an exception: an unrecognised band is a real possibility (an
    old token, a hand-edited claim) and the correct response to it is to refuse
    everything, which callers get for free by comparing against a value that is
    below every real band.
    """
    try:
        return AGE_BANDS.index(band)  # type: ignore[arg-type]
    except ValueError:
        return -1


# ── retrieval ────────────────────────────────────────────────────────────────


class KBChunk(BaseModel):
    """One retrieved slice of the knowledge base, with what it takes to cite it.

    `kb_id` is the knowledge-base row identifier ("ASP-042"), and it is required
    rather than optional on purpose. A chunk with no id cannot be cited, and an
    answer that cannot be cited is one this product does not serve -- so a
    chunk that reaches here without one is a bug in ingestion, not a chunk to
    quietly render without a reference.
    """

    kb_id: str
    title: str = ""
    content: str
    #: Ordering score. After fusion this is normalised rank agreement, 1.0
    #: meaning every retriever put it first. It orders; it does not measure.
    score: float = 0.0
    #: Cosine relevance from the dense retriever, 1.0 being identical.
    #:
    #: The only CALIBRATED similarity in the system, and therefore the only one
    #: `ground_check`'s floor can compare against. Carried separately from
    #: `score` because fusion overwrites that with a rank-derived number, and a
    #: floor applied to a rank means nothing -- every chunk a retriever returns
    #: ranks highly, including the twelve nearest neighbours of a question the
    #: corpus has never heard of.
    #:
    #: 0.0 on a chunk the dense side never saw (a BM25-only hit).
    relevance: float = 0.0
    #: Which retriever produced it, so a fusion result can be explained.
    #: "dense", "bm25" or "fused".
    source: str = "fused"
    metadata: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    """A reference the reader is shown, pointing at a knowledge-base row.

    Separate from `KBChunk` because they answer different questions. A chunk is
    *what the model was given*; a citation is *what the answer actually rests
    on*. Retrieving five chunks and citing two is the normal case, and
    collapsing the two types would lose that distinction exactly where
    `ground_check` needs it.
    """

    kb_id: str
    title: str = ""
    #: The sentence or clause in the answer this reference supports, when the
    #: grounding check could attribute one. Blank means "supports the answer
    #: generally", which is weaker but still a real citation.
    supports: str = ""


# ── reducers ─────────────────────────────────────────────────────────────────


#: The value a node returns to empty an accumulating field.
#:
#: An accumulating reducer has no way to express "start again" -- returning `[]`
#: appends nothing, which is the opposite of clearing. Every codebase with a
#: reducer eventually needs this, and the two ways of getting it are a sentinel
#: or a second non-accumulating field. A sentinel keeps the field count down and
#: puts the intent at the call site: `{"ui_directives": RESET}` says exactly
#: what it does.
#:
#: A STRING and not a singleton class, and that is not a style choice. The whole
#: state is checkpointed through msgpack, and a custom class raises
#: `Type is not msgpack serializable` the first time a turn is persisted -- on
#: the deployment with a database, which is the one nobody tests against first.
#: A string round-trips through every serialiser there is.
#:
#: Distinguishable from a real value because these fields hold lists of objects,
#: never a bare string. `None` would not do: `None` is what an ABSENT update
#: looks like, and a node that forgot to return a key would silently wipe the
#: field.
RESET = "__aspire_reset__"


def append_directives(
    left: list[UIDirective] | None, right: list[UIDirective] | None | str
) -> list[UIDirective]:
    """Collect directives from every node that emitted one this turn.

    Append rather than replace because the turn has several potential emitters
    -- an agent emitting quick replies, the widget planner emitting a widget,
    the QA agent emitting citations -- and each of them writing the whole list
    would mean whichever ran last silently deleted the others' work.

    Passing an empty list is therefore NOT how a node clears directives. Return
    `RESET`, which `hydrate` does at the start of every turn and `safety_out`
    does when it drops a turn's directives wholesale.
    """
    if right == RESET:
        return []
    return [*(left or []), *(right or [])]


def merge_citations(
    left: list[Citation] | None, right: list[Citation] | None | str
) -> list[Citation]:
    """Union of citations, first occurrence winning, order preserved.

    De-duplicated on `kb_id` because the same row legitimately arrives twice --
    once from BM25 and once from the dense retriever, fused -- and a reader
    should see one reference, not the same reference twice.

    Accepts `RESET` for the same reason `append_directives` does: last turn's
    citations must not be attributed to this turn's answer.
    """
    if right == RESET:
        return []
    merged: list[Citation] = []
    seen: set[str] = set()
    for citation in [*(left or []), *(right or [])]:
        if citation.kb_id in seen:
            continue
        seen.add(citation.kb_id)
        merged.append(citation)
    return merged


# ── agent-local state ────────────────────────────────────────────────────────
#
# TODO(C2/E1): these become real TypedDicts -- `app.agents.learn.state.LearningState`
# and the registration equivalent -- once those subgraphs exist. They are `Any`
# here rather than absent so the shape of `AspireState` is settled now and the
# subgraphs slot into a field that already exists; nothing outside those
# subgraphs is permitted to read into them.

LearningState = Any
RegistrationState = Any


class AspireState(TypedDict, total=False):
    """What every node receives and what any node may add to.

    `total=False` because nodes construct partial updates constantly -- a node
    returning `{"speak": True}` is the normal case, and a TypedDict that
    demanded every key would make each of those a type error.
    """

    # ── identity: written by `hydrate`, from token claims only ──────────────
    session_id: str
    #: None for an anonymous caller, which is a first-class state rather than an
    #: error. `access.allowed_agents` treats it as overriding persona entirely.
    user_id: str | None
    device_id: str
    persona: Persona
    age_band: AgeBand
    account_status: AccountStatus
    locale: Locale

    # ── conversation ────────────────────────────────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages]
    #: Everything older than the message window, compressed. PII-redacted before
    #: it is ever written -- see `pii.redact_for_summary` and the `persist` node.
    summary: str
    #: Who answered last turn. Drives classifier stickiness: a registration
    #: half-filled or a lesson half-taught must not be abandoned because one
    #: ambiguous sentence scored marginally higher somewhere else.
    active_agent: str | None
    #: Written by `guard` from the access matrix. Empty means a hard 403.
    allowed_agents: list[str]

    # ── retrieval ───────────────────────────────────────────────────────────
    retrieved: list[KBChunk]
    citations: Annotated[list[Citation], merge_citations]
    #: 0.0-1.0. How much of the generated answer is attributable to `retrieved`.
    #: Below the threshold in `agents/qa/nodes.py` the turn escalates instead of
    #: answering.
    groundedness: float
    #: The pronoun-resolved search query. Written by `rewrite_query`, read by
    #: retrieval. Kept in state rather than passed between the two nodes so a
    #: trace shows what was actually searched for -- a retrieval that returns
    #: nothing is nearly always a rewrite that went wrong, and without this
    #: there is no way to see that after the fact.
    qa_query: str

    # ── escalation ──────────────────────────────────────────────────────────
    #: Why this turn is going to a person, and a PII-redacted account of it.
    #: Written by whichever node decided to escalate, read by `escalate_agent`.
    #: Redaction happens at the WRITER, never here, so there is no path to a
    #: ticket that skips it.
    escalation_reason: str | None
    escalation_summary: str | None
    #: Written by `escalate_agent` once the ticket exists, so the reference is
    #: in state for the transcript and for a later turn to refer back to.
    escalation_ticket: str | None
    escalation_priority: str | None

    # ── agent-local (None when that agent is not running) ───────────────────
    learning: LearningState | None
    registration: RegistrationState | None

    # ── output contract ─────────────────────────────────────────────────────
    ui_directives: Annotated[list[UIDirective], append_directives]
    #: Tap targets. `safety_out` enforces that a learn_agent turn has 2-4 of
    #: these; the learn nodes generate them properly rather than relying on it.
    quick_replies: list[str]
    #: Whether the client should speak this turn. Defaults true for the two
    #: youngest bands, where reading is the barrier the product exists to work
    #: around.
    speak: bool

    # ── safety bookkeeping ──────────────────────────────────────────────────
    #: Flags raised by `safety_in`, consumed by the router and by escalation.
    #: A dict rather than typed fields because the set grows, and every consumer
    #: asks `flags.get(...)` rather than switching on all of them.
    safety_flags: dict[str, Any]
    #: Set when a node has decided the turn is over and no agent should run --
    #: a guard refusal, an injection block. `main_graph` routes straight to
    #: `safety_out` on it.
    halt_reason: str | None


def initial_state(
    *,
    session_id: str,
    user_id: str | None,
    device_id: str,
    persona: Persona,
    age_band: AgeBand,
    account_status: AccountStatus,
    locale: Locale = "en",
) -> AspireState:
    """A fully-populated state for a fresh turn.

    Exists so that every construction site -- the API, the tests, the eval
    harness -- produces the same shape. A state assembled ad hoc is a state
    missing `allowed_agents`, and a missing `allowed_agents` reads as "no agents
    permitted" in one place and raises a KeyError in another.
    """
    return AspireState(
        session_id=session_id,
        user_id=user_id,
        device_id=device_id,
        persona=persona,
        age_band=age_band,
        account_status=account_status,
        locale=locale,
        messages=[],
        summary="",
        active_agent=None,
        allowed_agents=[],
        retrieved=[],
        citations=[],
        groundedness=0.0,
        qa_query="",
        escalation_reason=None,
        escalation_summary=None,
        escalation_ticket=None,
        escalation_priority=None,
        learning=None,
        registration=None,
        ui_directives=[],
        quick_replies=[],
        speak=age_band in ("5-8", "9-12"),
        safety_flags={},
        halt_reason=None,
    )
