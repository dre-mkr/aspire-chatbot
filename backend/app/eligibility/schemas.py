"""Response models for the eligibility HTTP surface."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ThreadBody(BaseModel):
    thread_id: str = Field(min_length=1, max_length=128)


class StartBody(ThreadBody):
    language: str = Field(default="en", max_length=8)


class AnswerBody(ThreadBody):
    # One of the option tokens on the question being shown.
    value: str = Field(min_length=1, max_length=32)


class RestartBody(ThreadBody):
    language: str | None = Field(default=None, max_length=8)


class OptionOut(BaseModel):
    value: str
    label: str


class QuestionOut(BaseModel):
    id: str
    text: str
    help: str | None = None
    options: list[OptionOut]
    position: int
    total: int
    # The token already chosen here, when the person has been back.
    answered_with: str | None = None
    can_go_back: bool = False


class ChecklistItemOut(BaseModel):
    id: str
    title: str
    detail: str
    where: str
    signed_by: str | None = None
    caveat: str | None = None
    # An alternative to the item above it, not another thing to bring.
    alternative: bool = False


class StepOut(BaseModel):
    number: int
    title: str
    detail: str
    link: str | None = None
    link_label: str | None = None


class ResultOut(BaseModel):
    verdict: str
    criterion: str
    headline: str
    body: list[str]
    disclaimer: str
    unresolved: list[str] = Field(default_factory=list)
    mentor_question: str | None = None
    checklist: list[ChecklistItemOut] = Field(default_factory=list)
    steps: list[StepOut] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)
    contacts: list[str] = Field(default_factory=list)
    reminder_year: int | None = None


class StateOut(BaseModel):
    """The card's whole world: a question, or a result, never both."""

    active: bool
    language: str
    question: QuestionOut | None = None
    result: ResultOut | None = None
    answered: int = 0
    total: int = 0


class LabelsOut(BaseModel):
    """The card's own chrome, in the flow's language."""

    title: str
    subtitle: str
    progress: str
    back: str
    leave: str
    close: str
    restart: str
    checklist_heading: str
    steps_heading: str
    checked_note: str
    where_label: str
    signed_label: str
    contact_heading: str
    banner: str


class StateEnvelope(StateOut):
    labels: LabelsOut
