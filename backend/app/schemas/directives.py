"""What the server may tell the client to render, as a closed typed union.

A directive is the one channel through which the graph asks for UI. It travels
as its own SSE event, carrying its own ordinal, alongside the prose stream --
never inside it.

## Why not just put it in the text

Because then it is not a contract, it is a convention, and conventions get
parsed. The moment a directive is `<<quick_replies: ["a","b"]>>` embedded in a
token stream, three things follow immediately and all three have bitten this
kind of system before:

  * the client must parse partial JSON out of a stream that can split anywhere,
    so it renders half a widget or nothing at all;
  * a model that mentions the syntax while explaining something renders a
    control by accident;
  * the prose typewriter has to stop and wait to find out whether the text it
    is holding is text.

Separate events with ordinals solve all three. `i` is a monotonic counter over
everything the turn emits, so the client can put a directive back exactly where
it belongs in the prose without depending on the order packets happened to
arrive in.

## Forward compatibility is the client's job and this file's obligation

The frontend registry renders nothing at all for a `t` it does not recognise
(see `DirectiveRegistry.tsx`). That only works if this file never reuses a `t`
for a different shape. Adding a directive is free; changing one is not --
add a new `t` instead.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.widgets.schemas import ConceptWidget


class _Directive(BaseModel):
    """`extra="forbid"` for the same reason the widget schemas use it.

    A directive with a field the server did not mean to send is a directive
    somebody is about to render. Rejecting at the boundary keeps the union
    closed in fact and not merely in the type annotation.
    """

    model_config = ConfigDict(extra="forbid")


# ── quick replies ────────────────────────────────────────────────────────────


class QuickReplyOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: What the child reads. Four words at most for the learning agent; that cap
    #: lives in `safety_out` because it varies by band and this schema does not
    #: know the band.
    label: str = Field(min_length=1, max_length=60)
    #: What is actually sent when they tap. Usually the label, sometimes a fuller
    #: sentence so the transcript reads naturally rather than as a list of chips.
    value: str = Field(min_length=1, max_length=280)


class QuickRepliesDirective(_Directive):
    """The tap-not-type surface. The primary interaction for bands 5-8 and 9-12.

    Two to four options, because one is not a choice and five is a menu. The
    learning agent generates these on every teach and check node; `safety_out`
    re-prompts once if a learn turn arrives without them, and the client falls
    back to a single "Keep going" chip rather than leaving a dead end.
    """

    t: Literal["quick_replies"] = "quick_replies"
    options: list[QuickReplyOption] = Field(min_length=1, max_length=4)


# ── game ─────────────────────────────────────────────────────────────────────


class GameDirective(_Directive):
    """Launch one of the real game components. Never a game simulated in text.

    Carries no puzzle content and no answer -- the client fetches the game's own
    state from the games API, exactly as it does today. That is what keeps the
    answer out of the chat response, and `tests/games/test_no_answer_leak.py`
    exists to keep it that way.
    """

    t: Literal["game"] = "game"
    game: Literal["scramble", "true_false", "millionaire"]
    concept: str
    difficulty: Literal[1, 2, 3] = 1


# ── eligibility ──────────────────────────────────────────────────────────────


class EligibilityDirective(_Directive):
    """Open the guided eligibility check. Carries no rule and no verdict.

    The card is the answer, and the card holds the AUDITED rules -- every one of
    them cites the knowledge-base row it came from (`app/eligibility/rules.py`).
    Anything the model says in the same turn is a second, unaudited answer to
    the question the card is about to answer properly, which is why the node
    that emits this returns no prose at all.

    `language` is which copy the card opens in. It is the conversation's locale,
    resolved server-side from the session claims -- never a field the model
    chose, because a model that could pick the language could start a French
    speaker's check in English by deciding to.
    """

    t: Literal["eligibility"] = "eligibility"
    check: Literal["aspire_eligibility"] = "aspire_eligibility"
    language: Literal["en", "es", "fr"] = "en"


# ── upload ───────────────────────────────────────────────────────────────────


class UploadDirective(_Directive):
    """Ask for a document. Rendered as `UploadCard`, resumed via `Command(resume=)`.

    `slot` is the registration schema path being filled
    ("child.birth_certificate"), which is what lets the graph resume at the
    right place rather than re-deriving it from the conversation.
    """

    t: Literal["upload"] = "upload"
    slot: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=160)
    accepts: list[str] = Field(min_length=1, max_length=8)
    max_mb: int = Field(default=10, ge=1, le=50)
    help: str = Field(default="", max_length=300)


# ── review card ──────────────────────────────────────────────────────────────


class ReviewSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=120)
    #: `(slot, label, display_value)`. The display value is what a reviewer or a
    #: parent should see, which for PII is a masked form -- the review card is
    #: rendered in a chat transcript and the transcript is persisted.
    fields: list[tuple[str, str, str]] = Field(default_factory=list)
    #: Document ids only. The client exchanges them for short-lived signed URLs;
    #: no bytes and no storage keys ride on this.
    documents: list[str] = Field(default_factory=list)


class ReviewCardDirective(_Directive):
    """The whole application, grouped and editable, before it is submitted."""

    t: Literal["review_card"] = "review_card"
    sections: list[ReviewSection] = Field(min_length=1, max_length=12)


# ── chart ────────────────────────────────────────────────────────────────────


class ChartSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=80)
    #: Already computed, in Python, deterministically. The client plots; it does
    #: not calculate. `project_savings` in `agents/qa/tools.py` is the only thing
    #: that fills this in for a Q&A turn.
    points: list[float] = Field(max_length=200)


class ChartDirective(_Directive):
    """A projection the QA tools computed. Adults and 16-18 only in practice."""

    t: Literal["chart"] = "chart"
    kind: Literal["line", "bar", "stacked_bar"] = "line"
    series: list[ChartSeries] = Field(min_length=1, max_length=4)
    x_labels: list[str] = Field(default_factory=list, max_length=200)
    y_unit: Literal["xcd_cents", "count", "rate"] = "xcd_cents"


# ── progress ─────────────────────────────────────────────────────────────────


class ProgressDirective(_Directive):
    """End-of-session summary: streak, badge, what moved.

    `mastery_delta` is the number of concepts that went up this session, not a
    score. A child is never shown a mastery number -- it is an internal 0-3
    scale used for scheduling, and surfacing it would turn a lesson into a
    grade.
    """

    t: Literal["progress"] = "progress"
    badge: str | None = None
    streak: int = Field(default=0, ge=0)
    mastery_delta: int = Field(default=0)


# ── citations ────────────────────────────────────────────────────────────────


class CitationRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: str
    title: str = ""


class CitationsDirective(_Directive):
    """Where an answer came from. Emitted by the QA agent on every answer.

    Not optional and not decorative: an answer with no citations is an answer
    the grounding check should have refused, so an empty list here is a bug
    upstream rather than a turn with nothing to show.
    """

    t: Literal["citations"] = "citations"
    refs: list[CitationRef] = Field(min_length=1, max_length=8)


# ── escalated ────────────────────────────────────────────────────────────────


class EscalatedDirective(_Directive):
    """A human has the question now. Says who, and when to expect them."""

    t: Literal["escalated"] = "escalated"
    ticket_id: str
    eta: str = Field(default="", max_length=120)


# ── widget ───────────────────────────────────────────────────────────────────


class WidgetDirective(_Directive):
    """A concept widget, already validated through every gate.

    By the time a directive of this type exists, the payload has been through
    parse, schema, band, numeric-sanity, formula-domain, copy and budget checks.
    Nothing downstream re-validates it and nothing downstream should have to.
    """

    t: Literal["widget"] = "widget"
    payload: ConceptWidget


#: The union carried on the wire and stored in `AspireState.ui_directives`.
UIDirective = Annotated[
    Union[
        QuickRepliesDirective,
        GameDirective,
        EligibilityDirective,
        UploadDirective,
        ReviewCardDirective,
        ChartDirective,
        ProgressDirective,
        CitationsDirective,
        EscalatedDirective,
        WidgetDirective,
    ],
    Field(discriminator="t"),
]

#: Every `t` the server can emit. The frontend registry is checked against this
#: by hand today; if it ever drifts, an unknown type renders nothing rather than
#: throwing, which is the failure mode this list exists to keep boring.
DIRECTIVE_TYPES: frozenset[str] = frozenset(
    {
        "quick_replies",
        "game",
        "eligibility",
        "upload",
        "review_card",
        "chart",
        "progress",
        "citations",
        "escalated",
        "widget",
    }
)


def directive_payload(directive: Any) -> dict[str, Any]:
    """A directive as the JSON that goes on the wire.

    One function so that `mode="json"` is not something each emitter has to
    remember. Without it a `Decimal` or a `datetime` reaches `json.dumps` and
    the whole SSE stream dies on a field nobody was looking at.
    """
    return directive.model_dump(mode="json")
