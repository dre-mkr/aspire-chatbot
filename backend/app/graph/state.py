"""The single state object every node in the ASPIRE graph reads and writes."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from app.schemas.directives import UIDirective

# ── the four closed vocabularies identity is drawn from ──
# Literal rather than str, so an out-of-set value is a type error and not a runtime surprise.

Persona = Literal["stella", "orion", "aurora", "nova"]
AgeBand = Literal["5-8", "9-12", "13-15", "16-18", "adult"]
AccountStatus = Literal["prospect", "applicant", "beneficiary", "guardian"]
Locale = Literal["en", "es", "fr"]

#: Every band, youngest first.
AGE_BANDS: tuple[AgeBand, ...] = ("5-8", "9-12", "13-15", "16-18", "adult")

#: Bands that are legally and editorially children.
MINOR_BANDS: frozenset[str] = frozenset({"5-8", "9-12", "13-15"})


def band_index(band: str) -> int:
    """Where a band sits on the ladder, or -1 if it is not a band we know."""
    try:
        return AGE_BANDS.index(band)  # type: ignore[arg-type]
    except ValueError:
        return -1


# ── retrieval ────────────────────────────────────────────────────────────────


class KBChunk(BaseModel):
    """One retrieved slice of the knowledge base, with what it takes to cite it."""

    kb_id: str
    title: str = ""
    content: str
    #: Ordering score.
    score: float = 0.0
    #: Cosine relevance from the dense retriever, 1.0 being identical.
    relevance: float = 0.0
    #: Which retriever produced it, so a fusion result can be explained.
    source: str = "fused"
    metadata: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    """A reference the reader is shown, pointing at a knowledge-base row."""

    kb_id: str
    title: str = ""
    #: The question this row was authored to answer.
    question: str = ""
    #: Row text opening -- the `[ASP-xxx]` marker is stripped, so this panel is the only provenance.
    snippet: str = ""
    #: The clause in the answer this reference supports, when grounding could attribute one.
    supports: str = ""


# ── reducers ─────────────────────────────────────────────────────────────────


#: The value a node returns to empty an accumulating field.
RESET = "__aspire_reset__"


def append_directives(
    left: list[UIDirective] | None, right: list[UIDirective] | None | str
) -> list[UIDirective]:
    """Collect directives from every node that emitted one this turn."""
    if right == RESET:
        return []
    return [*(left or []), *(right or [])]


def merge_citations(
    left: list[Citation] | None, right: list[Citation] | None | str
) -> list[Citation]:
    """Union of citations, first occurrence winning, order preserved."""
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


# ── agent-local state ──
# TODO: these stay `Any` until the agent subgraphs declare their own state schemas.

LearningState = Any
RegistrationState = Any


class AspireState(TypedDict, total=False):
    """What every node receives and what any node may add to."""

    # ── identity: written by `hydrate`, from token claims only ──────────────
    session_id: str
    #: None for an anonymous caller, which is a first-class state rather than an error.
    #: Present but unproven for a visitor: a signed-out caller is still given an
    #: anonymous account row so their chats survive until they sign up.
    user_id: str | None
    #: Whether anybody proved who this is. `guard` reads this, not `user_id`.
    identity_proven: bool
    device_id: str
    persona: Persona
    age_band: AgeBand
    account_status: AccountStatus
    locale: Locale
    #: The language the reader switched to mid-conversation, if they did.
    #:
    #: Survives in the checkpoint, and `identity_from` must never write it.
    #: `hydrate` rewrites `locale` from the session token's claims on every turn,
    #: so a switch made on turn three is gone by turn four unless something puts
    #: it back -- this is what `detect_language` re-applies. Add it to
    #: `identity_from` and a Spanish session flips back to English on the very
    #: next message, which is the bug, not the fix.
    locale_override: Locale | None

    # ── conversation ────────────────────────────────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages]
    #: Everything older than the message window, compressed.
    summary: str
    #: Who answered last turn.
    context: Any
    active_agent: str | None
    #: Written by `guard` from the access matrix. Empty means a hard 403.
    allowed_agents: list[str]

    # ── retrieval ───────────────────────────────────────────────────────────
    retrieved: list[KBChunk]
    #: Ranked hits the reranker dropped, kept out of the model but used to build follow-up chips.
    qa_related: list[KBChunk]
    citations: Annotated[list[Citation], merge_citations]
    #: 0.0-1.0.
    groundedness: float
    #: The pronoun-resolved search query.
    qa_query: str

    # ── escalation: why this turn is going to a person, and the ticket that records it ──
    escalation_reason: str | None
    escalation_summary: str | None
    #: Written by `escalate_agent` once the ticket exists, so later turns can quote the reference.
    escalation_ticket: str | None
    escalation_priority: str | None
    #: `{intent_key: consecutive_unresolved_turns}`, at most one entry.
    decline_streak: dict[str, int]

    # ── agent-local (None when that agent is not running) ───────────────────
    learning: LearningState | None
    registration: RegistrationState | None

    # ── output contract ─────────────────────────────────────────────────────
    ui_directives: Annotated[list[UIDirective], append_directives]
    #: Tap targets.
    quick_replies: list[str]
    #: Whether the client should speak this turn.
    speak: bool

    # ── safety bookkeeping: flags raised by `safety_in` and read by the nodes after it ──
    safety_flags: dict[str, Any]
    #: Set when a node ends the turn early -- a guard refusal, an injection block.
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
    identity_proven: bool = True,
) -> AspireState:
    """A fully-populated state for a fresh turn.

    `identity_proven` was declared on `AspireState` and never set here, so a
    state built through this helper read it as absent -- and absent is falsy.
    Nothing in `app/` calls this (production builds state in `hydrate`, which
    reads the flag off the token), so it only ever bit fixtures: the moment
    anything keyed on the flag, every fixture silently became a signed-out
    visitor. Defaulted to True to match `decode_session_token`, and because a
    fixture naming a `user_id` and an `account_status` means an established
    session. A test that wants a visitor now has to say so.
    """
    return AspireState(
        session_id=session_id,
        user_id=user_id,
        device_id=device_id,
        persona=persona,
        age_band=age_band,
        account_status=account_status,
        locale=locale,
        # No switch has happened yet. Set here rather than left absent, for the
        # reason `identity_proven` above was: a field declared on the state and
        # never written by this helper reads as absent, and absent is falsy in
        # exactly the places a fixture stops resembling a real session.
        locale_override=None,
        identity_proven=identity_proven,
        messages=[],
        summary="",
        context=None,
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
        decline_streak={},
        learning=None,
        registration=None,
        ui_directives=[],
        quick_replies=[],
        speak=age_band in ("5-8", "9-12"),
        safety_flags={},
        halt_reason=None,
    )
