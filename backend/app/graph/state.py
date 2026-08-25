"""The single state object every node in the ASPIRE graph reads and writes."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from app.schemas.directives import UIDirective

# ── the four closed vocabularies identity is drawn from ──
# Literal rather than str, so an out-of-set value is a type error and not a runtime surprise.

Persona = Literal["stella", "orion", "aurora", "nova", "guest"]
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
    #: The `documents.source_url` column, carried as its own field rather than
    #: left in `metadata` alone. `metadata` is whatever the CSV happened to hold
    #: and a row can reach here without it -- BM25 builds chunks from the corpus
    #: index, not from a retriever row -- so provenance gets a declared home.
    source_url: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def provenance(self) -> Any:
        """This chunk's source, named and validated, or None when it has none."""
        from app import sources

        return sources.describe(self.metadata, stored_url=self.source_url)


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

    # ── where the row came from ──
    #
    # Filled from `documents.source_url` by way of `app.sources`, never by the
    # model. A row whose stored URL is missing, internal or unparseable arrives
    # here with `url` empty and the rest of the naming intact, which is the
    # difference between "we cannot link this" and "we have no source".
    #: A validated https/http URL, or "" when this source has no public page.
    #:
    #: Named `source_url` to match the column it comes from and the wire field
    #: the front end reads. Empty is meaningful: a claim the reader cannot check
    #: should look different from one they can, so the panel can render the
    #: difference rather than guess at it.
    source_url: str = ""
    #: Whose source it is -- "ASPIRE", "Eastern Caribbean Central Bank".
    site: str = ""
    #: Which page of theirs -- "Frequently asked questions".
    page: str = ""
    #: The host, for the line under the title.
    domain: str = ""
    #: The corpus row's `as_of` date: when it was last checked against the source.
    updated: str = ""


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

    #: Whether the reader has left the language on Automatic.
    #:
    #: An answer-shaping preference, not a claim about who they are, so it rides
    #: in the body beside `simple_mode` rather than in the signed token -- and
    #: like `simple_mode` it is written every turn, because it can be changed
    #: between two questions.
    #:
    #: False is a PIN, not an absence. A reader who picked Espanol has said
    #: something, and detection must stop overruling them the moment they write
    #: one English sentence to a Spanish assistant.
    auto_language: bool

    #: Set when the reader asked for a story and was asked what about.
    #:
    #: The whole storytelling feature is two turns, and this is the latch
    #: between them. It is also the ONLY way a story can begin: nothing in the
    #: planner, the tutor or the router can set it, so the assistant cannot
    #: start telling stories at a reader who did not ask.
    awaiting_story_topic: bool

    #: What the story should be about, for the one turn that tells it.
    story_topic: str | None

    #: The reader's chosen personality overlay ("coach", "limer", ...), or "".
    #: A preference, not identity: it rides the request body like simple_mode.
    overlay: str

    #: The Tin: {"coins": int}. Only ever fills. See `app/graph/tin.py`.
    tin: dict | None

    #: Story artifacts earned by finishing played stories: [{"name","emoji","topic"}].
    collectibles: list

    #: A standing savings pledge: {"amount_line": str, "goal": str}.
    #:
    #: Written when the reader signs the pledge card, read by the QA shaping
    #: layer so every later turn can keep the goal in view. Thread-scoped.
    pledge: dict | None

    #: The latch for the Azuri/Imani learn-vs-teach clarifier.
    #:
    #: An educator or a parent who asks to be TAUGHT is ambiguous in a way a
    #: child never is: they may be learning for themselves, or preparing to
    #: teach it to their students or their own child. Set when we have asked
    #: which; read on the next turn to interpret the answer. Like
    #: `awaiting_story_topic`, this is the only thing that starts the exchange.
    awaiting_learner_purpose: bool

    #: The answer, remembered for the rest of the session: "self", "students"
    #: or "child". Empty until asked and answered. This is the "ask ONCE" half:
    #: once it is set, the clarifier never fires again this session.
    learner_purpose: str

    #: The lesson request that triggered the clarifier, held so the turn that
    #: answers "for myself" can resume "teach me about budgeting" rather than
    #: teaching a lesson called "for myself".
    pending_learning: str | None

    #: The band a PREVIEW should be written at, when it is not the reader's own.
    #:
    #: A parent asking to see her nine-year-old's lesson. Read only by
    #: `learning_preview` and `learning_sample`; `learn_agent` ignores it, which
    #: is what stops it being a way for a reader to move their own band.
    preview_band: str | None

    #: A story still being told, across turns: {"topic": str, "beat": int}.
    #:
    #: `story_topic` is cleared by `hydrate` on every turn, deliberately -- left
    #: set, every later question would be answered as another story. That is
    #: right for a story that ends when it ends, and it is why a story could not
    #: continue: nothing survived the turn that told it.
    #:
    #: This does survive, like `locale_override` and for the same reason. It
    #: holds the thread the reader is in the middle of, and `hydrate` must never
    #: clear it -- only the reader ends an arc, by saying so or by reaching the
    #: last beat.
    story_arc: dict[str, Any] | None

    #: Every video already offered in this conversation, whether or not it was
    #: watched.
    #:
    #: Offering the same film again because a second question also mentioned
    #: saving is the exact "intrusive" the brief asks this feature not to be. An
    #: offer declined is an answer; asking again is not listening. Grows to the
    #: size of the catalog and stops.
    videos_offered: list[str]

    #: The video offered at the end of the last answer, if one was.
    #:
    #: Held rather than re-derived, because the acceptance is not the question.
    #: "Watch the video" carries no topic, so matching it against the catalog
    #: again finds nothing; what it refers to is the offer, and the offer is
    #: what has to be remembered. Cleared as soon as it is taken or the reader
    #: asks something else, so a yes three turns later opens nothing.
    offered_video: str | None
    #: The pathway step offered last turn, for the same reason as the line above:
    #: never twice running, and a chip the reader ignored is a chip they have
    #: answered. `app/pathway/suggest.py` reads it and refuses when it is set.
    suggested_step: str | None

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
    #: The reader has the "Explain it simply" control on for this turn.
    #:
    #: Per-turn, not per-session: it is rewritten by `hydrate` from the request
    #: body every turn, so switching it off takes effect on the next answer
    #: rather than persisting in the checkpoint.
    simple_mode: bool

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
        auto_language=True,
        awaiting_story_topic=False,
        story_topic=None,
        overlay="",
        collectibles=[],
        tin=None,
        pledge=None,
        awaiting_learner_purpose=False,
        learner_purpose="",
        pending_learning=None,
        preview_band=None,
        story_arc=None,
        offered_video=None,
        suggested_step=None,
        videos_offered=[],
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
