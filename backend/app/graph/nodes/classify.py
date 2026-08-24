"""Which agent answers this turn."""

from __future__ import annotations

import re

import json
import logging
from typing import Any, Final

from pydantic import BaseModel, Field

from app.config import get_settings
from app.graph.state import AspireState

logger = logging.getLogger(__name__)

#: One line each.
#:
#: These are not documentation. They are the only thing the router reads before
#: deciding who answers, so they ARE the routing logic, written in English, and
#: five rules make them work: each one is self-contained, states a boundary
#: rather than a summary, names the agent it is most easily confused with, uses
#: the phrasings readers actually type, and leads with what makes it different
#: rather than what it shares.
#:
#: Two things were wrong. `qa_agent` ended with "how the programme works", which
#: advertised the tutor's job on the fact-lookup agent, so every "how does..."
#: question was pulled towards the summariser -- three true facts, correctly
#: cited, never joined into a cause. And the two band-filtered variants opened
#: with "The same factual questions", which refers to a line the router may never
#: be shown: it sees only the agents this reader is ALLOWED, so a child sees
#: `qa_agent_limited` with no `qa_agent` above it for "the same" to point at.
#: That happened for exactly the two audiences that matter most here, children
#: and signed-out visitors.
AGENT_DESCRIPTIONS: dict[str, str] = {
    "learn_agent": (
        "Explaining how or why something about money works, and teaching a "
        "lesson step by step: \"how does the money grow?\", \"why does starting "
        "early matter?\", \"what is compound interest?\". Also asking a check "
        "question, playing a learning game, or continuing a lesson already under "
        "way. Choose this whenever the reader wants to understand a mechanism "
        "rather than be told a rule -- including when that mechanism is part of "
        "ASPIRE itself."
    ),
    "learning_preview": (
        "A guardian looking at what their child is being taught, rather than "
        "being taught themselves: what is in the lessons, what has been covered "
        "so far, and how a topic is explained to their child."
    ),
    "learning_sample": (
        "A signed-out visitor who wants to understand how something works, or to "
        "try a short taste of a lesson: \"how does saving grow?\", \"show me what "
        "you teach\". Explaining a mechanism, not quoting a rule. "
        "NOT for a question about the programme's rules, about an account, about "
        "the reader's own circumstances, or about what material exists for a "
        "class -- those are facts to look up, not mechanisms to explain."
    ),
    "qa_agent": (
        "Looking up a stated fact about ASPIRE: who is eligible, which documents "
        "are needed, amounts, dates, deadlines, branches and opening "
        "arrangements. The answer is a rule or a figure that is written down "
        "somewhere. Not for \"how does it work?\" or \"why?\" -- those belong to "
        "learn_agent."
    ),
    "qa_agent_limited": (
        "Stated facts for a younger reader -- who is eligible, which documents "
        "are needed, amounts, dates, deadlines -- over the part of the knowledge "
        "base written for them. Rules and figures, not explanations of how "
        "something works."
    ),
    "qa_agent_public": (
        "Stated facts for a signed-out visitor -- who is eligible, which "
        "documents are needed, amounts, dates, deadlines -- over public "
        "information only. Rules and figures, not explanations of how something "
        "works."
    ),
    "register_agent": (
        "Filling in an ASPIRE application: collecting a guardian's and a "
        "child's details, uploading documents, reviewing and submitting."
    ),
    "register_agent_step1": (
        "Starting an application before signing in -- the first few questions "
        "only. Only when the reader has said they want to APPLY or sign up. "
        "NOT for someone who merely mentioned a child, a parent or a name, and "
        "never for a question about the assistant itself."
    ),
    "servicing_agent": (
        "Something about an account that already exists: balance, statements, "
        "changing details, a payment that has not arrived."
    ),
}

# `escalate_agent` has no description because `routable()` drops it before the menu is built.

#: What the model says when none of the handlers is right.
#:
#: A ROUTER FORCED TO CHOOSE WILL ALWAYS CHOOSE. Given ten handlers and no way
#: to decline, "What is your name?" does not fail to route -- it routes
#: confidently, and the nearest description wins. It landed on
#: `register_agent_step1` ("starting an application, the first few questions"),
#: whose reply is "And how are you related to the child?".
#:
#: Abstaining is not a failure mode here. `_coerce` already knows what to do
#: with a name it does not recognise: fall back to the row's first agent, which
#: is Q&A by construction, because Q&A is the default for every reader. Saying
#: "none" reaches that answer HONESTLY instead of arriving there through a
#: wrong guess -- and it lands in the log as an abstention rather than as a
#: hallucination, which is the difference between a signal and noise.
ABSTAIN: Final[str] = "none"

_SYSTEM = (
    "You route one message to one handler. Choose from the list you are given, "
    'or reply with "none" if no handler on the list is right for it. '
    "Reply with JSON only: "
    '{"agent": "<name from the list, or none>", "confidence": <0.0-1.0>, '
    '"reason": "<six words or fewer>", "role": "<see below, or empty>"}. '
    "Confidence is how sure you are that the message belongs to that handler "
    "rather than another one on the list. Use a value below 0.5 when the "
    "message is short, ambiguous, or could belong to two of them. "
    'Prefer "none" over a handler you are guessing at: a message that is small '
    "talk, a greeting, a name, or about the assistant itself belongs to no "
    "handler on this list, and choosing the closest one is worse than saying so."
    "\n\n"
    'Also return "role": who the reader is speaking AS, if this message says or '
    "clearly implies it. One of:\n"
    "  teacher  - has a class of their own: \"my Form 2s\", \"my Grade 4s\", "
    "\"period 3\", \"how do I teach this\", asking for an activity or worksheet\n"
    "  educator - responsible beyond one classroom: \"our school\", \"my staff\", "
    "\"the department\", policy, rolling it out, adopting it, what it costs, who "
    "is accountable, data, consent, safeguarding\n"
    "  parent   - speaking about their own child: \"my daughter\", \"I have two "
    "children\", \"as a parent\"\n"
    "  learner  - an ADULT working on their OWN money: \"I want to get "
    "better with money\", \"how do I stop living paycheck to paycheck\", "
    "\"I never learned to budget\", \"help me get my spending under "
    "control\", \"what should I do with my savings\". First person, their "
    "own situation, a real ask for help -- not a child answering a lesson.\n"
    '  ""       - nothing in this message says which. Common, and the right '
    "answer whenever the reader has only named a TOPIC with no first-person "
    "stake: \"what is compound interest\", \"tell me about saving\". Asking "
    "about lessons does not make someone a teacher. But \"I\" plus their own "
    "money -- a problem they have, a habit they want -- is a learner, and the "
    "commonest adult on this service.\n"
    "Saying what they HAVE is stating a role, even without the words "
    '"as a": "I have two children" and "J\'ai deux enfants" are parent; '
    '"my Form 2s" is teacher. Saying what they WANT is not.\n'
    "The same person can be more than one and can change between messages, so "
    "read only THIS message, not the conversation."
)


class Classification(BaseModel):
    """What the classifier returns, after validation."""

    agent: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    #: Who the reader spoke as this turn, if they said. See `_SYSTEM`.
    #:
    #: A field on the call that already happens, rather than a second call or a
    #: pattern list. The patterns this replaces could only match what somebody
    #: thought of in advance -- they had "mes enfants" and not "j'ai deux
    #: enfants", which is exactly the phrasing a French parent uses.
    role: str = ""
    #: True when the model's choice was discarded.
    coerced: bool = False
    #: True when stickiness kept the turn in `active_agent` against a differing proposal.
    sticky: bool = False


#: Agents the router may never select, whatever the access matrix granted.
UNROUTABLE: frozenset[str] = frozenset({"escalate_agent"})

#: Agents the access matrix grants that have no implementation behind them.
#:
#: EMPTY NOW, and `servicing_agent` leaving it is the point.
#:
#: It was here because it had no subgraph, and routing a reader to a placeholder
#: was worse than answering their account question from the corpus. That reversed
#: the moment the placeholder became an answer: it now names where a balance
#: actually lives -- quarterly statements, the portal, the National Bank, the
#: team -- in three languages, which is the true answer and the only one this
#: system can honestly give. There is no balance in this database to look up.
#:
#: What the exclusion cost while it stood: "what is my balance", "my deposit has
#: not shown up yet", "can you send me a statement" and "i need to change the
#: address on the account" all went to `qa_agent`, which answered them from the
#: corpus -- general facts about how ASPIRE accounts work, to someone asking
#: about theirs. Four of the five misses in
#: `test_routing_accuracy_against_the_labelled_set` were exactly these, and they
#: were unwinnable: the labelled set asks for an agent `routable` forbade.
#:
#: A stub with nothing to say belongs here. A stub whose answer is the right
#: one does not.
UNBUILT: frozenset[str] = frozenset()


def routable(allowed: list[str]) -> list[str]:
    """The granted agents the router may actually choose between."""
    excluded = UNROUTABLE | UNBUILT
    return [agent for agent in allowed if agent not in excluded]


def agent_menu(allowed: list[str]) -> str:
    """The list the classifier is shown."""
    lines = []
    for agent in allowed:
        description = AGENT_DESCRIPTIONS.get(agent, "")
        lines.append(f"- {agent}: {description}" if description else f"- {agent}")
    return "\n".join(lines)


#: The only role values the router may return. Anything else is dropped.
#:
#: A closed set, checked here rather than trusted: this value chooses which
#: slice of the corpus a reader is offered, and a model inventing "headmaster"
#: would silently mean "no role at all" further down. Better to know.
ROLES: frozenset[str] = frozenset({"teacher", "educator", "parent", "learner"})


def _parse(raw: str) -> tuple[str, float, str, str] | None:
    """Read the model's JSON, tolerating the wrappers small models add."""
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    agent = str(data.get("agent") or "").strip()
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    role = str(data.get("role") or "").strip().lower()
    if role and role not in ROLES:
        logger.info("Router returned an unknown role %r; ignoring it.", role[:40])
        role = ""
    return (
        agent,
        max(0.0, min(1.0, confidence)),
        str(data.get("reason") or "")[:120],
        role,
    )


def _coerce(
    proposed: str, confidence: float, reason: str, state: AspireState
) -> Classification:
    """Turn the model's answer into a decision that is certainly permitted."""
    allowed = list(state.get("allowed_agents") or [])
    active = state.get("active_agent")

    if proposed in allowed:
        return Classification(agent=proposed, confidence=confidence, reason=reason)

    if proposed.lower() == ABSTAIN:
        # INFO, not WARNING. The model was asked whether any handler fits and
        # said no; that is the option working, not a fault. Logged so a week of
        # these can be read as a list of what the menu does not cover.
        logger.info(
            "Classifier abstained for session %s (%s); using the row default %r.",
            state.get("session_id"),
            reason or "no reason given",
            allowed[0] if allowed else None,
        )
        if allowed:
            return Classification(
                agent=allowed[0], confidence=confidence, reason=reason, coerced=True
            )

    if proposed:
        # WARNING: a name outside the list is a hallucination or an attempt, and worth watching.
        logger.warning(
            "Classifier proposed %r for session %s, which is not in %s; coercing.",
            proposed[:40],
            state.get("session_id"),
            allowed,
        )

    if active in allowed:
        return Classification(
            agent=str(active), confidence=confidence, reason=reason, coerced=True
        )
    return Classification(
        agent=allowed[0], confidence=confidence, reason=reason, coerced=True
    )


#: The agents whose whole job is to teach. Naming them once, here, because two
#: separate rules below need the same list and they must not drift apart.
TEACHING_AGENTS: tuple[str, ...] = (
    "learn_agent",
    "learning_sample",
    "learning_preview",
)


#: A message that is asking something, rather than answering something.
#:
#: Quiz answers are short and declarative: "Saving", "Spending", "true", "I
#: think a loan". A question is not, and the difference is what this reads.
_ASKS_SOMETHING = re.compile(
    r"\?\s*$"                                     # ends in a question mark
    r"|^\s*(what|who|when|where|why|how|which|can|could|do|does|did|is|are|"
    r"should|will|would|am|have|has|tell me|explain)\b",
    re.IGNORECASE,
)


#: A reader describing themselves, which no check question asks them to do.
_ABOUT_THE_READER = re.compile(
    r"^\W*(?:well|so|okay|ok|actually)?\W*(?:"
    r"as\s+(?:an?|the)\s+\w+"
    r"|i\s+(?:have|want|need|am|was|would\s+like|work|teach|run|'m)\b"
    r"|my\s+(?:child|children|son|daughter|kid|kids|class|students|school|pupils)\b"
    r"|we\s+(?:have|are|want|need)\b"
    # Spanish
    r"|(?:yo\s+)?(?:tengo|quiero|necesito|soy|trabajo)\b"
    r"|como\s+(?:docente|maestra?|profesora?|madre|padre)\b"
    r"|mis?\s+(?:hijos?|hijas?|alumnos?|clase)\b"
    # French
    r"|j'?(?:ai|e\s+(?:veux|suis|travaille))\b"
    r"|en\s+tant\s+qu"
    r"|mes?\s+(?:enfants?|fils|filles?|[eé]l[eè]ves|classe)\b"
    r")",
    re.IGNORECASE,
)


def _is_about_the_reader(state: AspireState) -> bool:
    """Whether this turn describes the reader rather than answering a question."""
    text = (_latest_user_text(state) or "").strip()
    return bool(text) and bool(_ABOUT_THE_READER.search(text))


#: The agents that walk a guardian through an application.
#:
#: Kept here rather than imported from `cards`, which imports this module.
REGISTRATION_AGENTS: tuple[str, ...] = (
    "register_agent",
    "register_agent_step1",
)


#: An outright question, for a reader who is part-way through an application.
#:
#: Deliberately NARROWER than `_ASKS_SOMETHING`, which also opens on `can`,
#: `do`, `is`, `are`, `will`, `have`. Those are safe to treat as questions
#: inside a lesson, where the alternative is a quiz answer. They are not safe
#: here, because the alternative is a slot answer -- and "Will" is a child's
#: name, which `\bwill\b` would read as a question and route away from the
#: very form that asked for it.
#:
#: A question mark, or a wh-word. Nothing else.
_ASKS_OUTRIGHT = re.compile(
    r"\?\s*$"
    r"|^\s*(what|who|whose|when|where|why|how|which|tell me|explain)\b"
    # Spanish and French, which the form is also asked in.
    r"|^\s*(qu[eé]|qui[eé]n(?:es)?|cu[aá]ndo|d[oó]nde|por\s+qu[eé]|c[oó]mo|cu[aá]l(?:es)?)\b"
    r"|^\s*(que|qui|quand|o[uù]|pourquoi|comment|quel(?:le)?s?)\b",
    re.IGNORECASE,
)


def _is_an_outright_question(state: AspireState) -> bool:
    """Whether this turn asks something, judged strictly. See `_ASKS_OUTRIGHT`."""
    text = (_latest_user_text(state) or "").strip()
    return bool(text) and bool(_ASKS_OUTRIGHT.search(text))


def _is_a_question_not_an_answer(state: AspireState) -> bool:
    """Whether this turn asks something rather than answering the last thing."""
    text = (_latest_user_text(state) or "").strip()
    if not text:
        return False
    return bool(_ASKS_SOMETHING.search(text))


#: Where a guardian is parked after her question is answered.
#:
#: Only these. A reader who left the form for a LESSON must not be yanked back
#: out of it by `_resume_registration` -- a quiz answer ("Saving", "true") is
#: not a question either, and would match every one of its conditions.
_QA_AGENTS: tuple[str, ...] = ("qa_agent", "qa_agent_limited", "qa_agent_public")


def _awaiting_slot(state: AspireState) -> str | None:
    """The registration slot this session is part-way through, if any."""
    raw = state.get("registration")
    if not isinstance(raw, dict):
        return None
    awaiting = raw.get("awaiting")
    return str(awaiting) if awaiting else None


def _resume_registration(
    decision: Classification, state: AspireState
) -> Classification | None:
    """An application left waiting mid-slot takes its own answer back.

    The escape in `apply_stickiness` lets a guardian ask a question without it
    being graded as a slot answer. That leaves her parked in QA with the form
    still open -- and measured against the real classifier, 23 August 2026, the
    one-word reply the interface itself offers as a chip does not get her back:

        "Grandmother"           -> qa_agent_public  0.40   (stranded)
        "I am her grandmother"  -> register_agent   0.90

    So the form reclaims a weak turn. Weak only: a confident proposal is a real
    change of subject -- "play a game" is not an answer to anything -- and it
    wins, exactly as it does everywhere else here.
    """
    if _awaiting_slot(state) is None:
        return None
    if state.get("active_agent") not in _QA_AGENTS:
        return None
    # She is asking again, not answering. The escape owns this turn.
    if _is_an_outright_question(state):
        return None

    allowed = state.get("allowed_agents") or []
    # The classifier PROPOSING the form is the strongest signal there is, and it
    # was the thing being thrown away: measured 23 August 2026, "Grandmother"
    # came back as `register_agent@0.40 'ambiguous single word'` -- right agent,
    # honest confidence -- and stickiness then replaced it with the QA agent she
    # was parked in, because 0.40 is under the threshold. Below the threshold is
    # exactly where a one-word answer lives.
    proposed_the_form = decision.agent in REGISTRATION_AGENTS
    target = (
        decision.agent
        if proposed_the_form and decision.agent in allowed
        else next((name for name in REGISTRATION_AGENTS if name in allowed), None)
    )
    if target is None:
        return None
    # A confident move somewhere else entirely is a real change of subject.
    if (
        not proposed_the_form
        and decision.confidence > get_settings().classifier_stickiness_threshold
    ):
        return None

    logger.info(
        "Returning session %s to %s: an application is waiting on %r and %s was "
        "only proposed at %.2f.",
        state.get("session_id"),
        target,
        _awaiting_slot(state),
        decision.agent,
        decision.confidence,
    )
    return Classification(
        agent=target,
        confidence=decision.confidence,
        reason="an application is waiting on a slot",
        sticky=True,
    )


def apply_stickiness(decision: Classification, state: AspireState) -> Classification:
    """Keep an ongoing flow unless the proposal clears the threshold."""
    resumed = _resume_registration(decision, state)
    if resumed is not None:
        return resumed

    active = state.get("active_agent")
    if not active or active not in (state.get("allowed_agents") or []):
        return decision
    if decision.agent == active:
        return decision

    # A move INTO teaching is never held back.
    #
    # Without this, the routing fix only works on the first turn. A reader asks
    # "what is compound interest", the classifier correctly proposes the tutor at
    # around 0.7, the threshold is 0.75, and stickiness quietly keeps them in the
    # Q&A agent -- which answers by listing facts instead of teaching. That is
    # precisely the behaviour the client has described, and it survives every fix
    # made upstream of this function because it happens after them.
    #
    # Stickiness exists to stop a flow being interrupted. Teaching IS the flow
    # this product is for; Q&A is what happens when there is nothing to teach. So
    # the guard only ever protects a teaching agent from being left, never a
    # non-teaching one from being entered.
    if decision.agent in TEACHING_AGENTS and active not in TEACHING_AGENTS:
        logger.info(
            "Letting %s take session %s from %s at %.2f: a move into teaching is "
            "exempt from stickiness.",
            decision.agent,
            state.get("session_id"),
            active,
            decision.confidence,
        )
        return decision

    # A QUESTION is never scored as a quiz answer.
    #
    # The exemption above is one-way on purpose: teaching is easy to enter and,
    # by design, hard to leave. What that had no exit for was a reader who is
    # inside a lesson and asks about something else entirely. Below the
    # threshold they stayed in the tutor, and the tutor read their question as
    # an attempt at its last check question.
    #
    # Measured on production, 23 August 2026, signed out:
    #   Azuri  "What have you got for my Form 3 class?"
    #          -> "You move EC$25 into your account instead of spending it this
    #             week. What is that?"        [Saving | Spending]
    #   Azuri  "What are my safeguarding obligations?"
    #          -> "Close. Ask yourself whether the money left your account or
    #             moved within it."           [Let me try again | Show me the answer]
    #   Imani  "Is my money safe?"  -> the same EC$25 quiz question.
    #
    # A teacher asking about child safeguarding was told "Close." Both adult
    # personas were worst hit, because a parent and a teacher ask the most
    # questions that are not lessons.
    #
    # So the door opens both ways for a QUESTION and stays one-way for
    # everything else. A quiz answer is short and declarative -- "Saving",
    # "true", "I think a loan" -- and none of those match, so a lesson under way
    # is protected exactly as before.
    # ...and neither is a reader telling you about THEMSELVES.
    #
    # The question escape above was half of it. Measured on production again,
    # 23 August 2026, both adult personas, both still trapped because neither
    # message is a question:
    #
    #   Imani  "Well I have 2 children"
    #          -> "Think about which plan survives contact with December."
    #                                         [Let me try again | Show me the answer]
    #   Azuri  "As an educator I want to prepare a lesson"
    #          -> answered as a learner, with learner chips.
    #
    # A parent volunteering that they have two children was graded as a wrong
    # answer and offered a hint. That is the same one-way door, entered by a
    # statement rather than a question.
    #
    # A quiz answer is about the MATERIAL -- "Saving", "true", "I think a loan".
    # These are about the READER, which no check question ever asks for. "I
    # think" is deliberately not in the set: it is how a learner hedges before
    # answering, and it must stay inside the lesson.
    if (
        active in TEACHING_AGENTS
        and decision.agent not in TEACHING_AGENTS
        and (_is_a_question_not_an_answer(state) or _is_about_the_reader(state))
    ):
        logger.info(
            "Letting %s take session %s from %s at %.2f: the reader asked a "
            "question rather than answering one.",
            decision.agent,
            state.get("session_id"),
            active,
            decision.confidence,
        )
        return decision

    # The same one-way door, on the registration side.
    #
    # The escape above is gated on `active in TEACHING_AGENTS`, and an
    # application is not a lesson, so a guardian part-way through one had no
    # exit at all. Measured on aspire.eccugenai.app, 23 August 2026, signed out:
    #
    #   "I want to sign up"
    #       -> "And how are you related to the child?"
    #   "Are there tutorials to help me sign up my child?"
    #       -> "Pick the closest one -- mother, father, grandmother, ..."
    #   "Grandmother"
    #       -> the tutorials answer, a turn late, and the relationship dropped
    #
    # Her question was read as a bad answer to the relationship slot. The slot
    # was re-asked, and because nothing had answered the question it was still
    # the salient one in the history -- so the NEXT turn answered it and threw
    # away the relationship. The application could not move either way.
    #
    # `_is_an_outright_question`, not `_is_a_question_not_an_answer`, and
    # `_is_about_the_reader` deliberately not consulted at all: "I am her
    # grandmother", "My child is seven", "I have two children" are what this
    # form is FOR. Reading those as a bid to leave would break the flow the
    # escape exists to protect.
    # Not `decision.agent not in REGISTRATION_AGENTS`, which is what this first
    # said and what let the reported turn through unchanged. The classifier
    # proposed the FORM for her question, while its own reason said otherwise:
    #
    #   "Are there tutorials to help me sign up my child?"
    #       -> register_agent@0.40 'asking for tutorials, not applying'
    #
    # It had understood her exactly and routed her to the thing that could not
    # answer. So the question decides this, not the proposal -- as long as the
    # proposal is weak enough to be worth overruling.
    if (
        active in REGISTRATION_AGENTS
        and _is_an_outright_question(state)
        and decision.confidence <= get_settings().classifier_stickiness_threshold
    ):
        answering = (
            decision.agent
            if decision.agent in _QA_AGENTS
            else next(
                (
                    name
                    for name in _QA_AGENTS
                    if name in (state.get("allowed_agents") or [])
                ),
                None,
            )
        )
        if answering is not None:
            logger.info(
                "Letting %s take session %s from %s at %.2f: the guardian asked "
                "a question rather than answering the slot.",
                answering,
                state.get("session_id"),
                active,
                decision.confidence,
            )
            return Classification(
                agent=answering,
                confidence=decision.confidence,
                reason="a question, not a slot answer",
            )

    threshold = get_settings().classifier_stickiness_threshold
    if decision.confidence > threshold:
        return decision

    logger.info(
        "Staying in %s for session %s: %s proposed at %.2f, below the %.2f "
        "stickiness threshold.",
        active,
        state.get("session_id"),
        decision.agent,
        decision.confidence,
        threshold,
    )
    return Classification(
        agent=str(active),
        confidence=decision.confidence,
        reason=decision.reason,
        sticky=True,
    )


def resolve_classifier_model() -> str:
    """Which model actually runs the router here."""
    settings = get_settings()
    configured = settings.classifier_model
    provider = configured.split(":", 1)[0].lower()

    has_key = {
        "anthropic": bool(settings.anthropic_api_key),
        "openai": bool(settings.openai_api_key),
    }.get(provider)

    if has_key is False:
        logger.warning(
            "CLASSIFIER_MODEL is %r but there is no %s key; routing will use "
            "CHAT_MODEL (%s) instead. Set CLASSIFIER_MODEL to a small model of "
            "your own provider -- routing does not need the answer model.",
            configured,
            provider,
            settings.chat_model,
        )
        return settings.chat_model
    return configured


def build_classifier_model():
    """The small model this node uses."""
    from langchain.chat_models import init_chat_model

    settings = get_settings()
    chosen = resolve_classifier_model()
    kwargs: dict[str, Any] = {}
    # Zero temperature where the provider accepts it.
    if not chosen.startswith("openai:gpt-5"):
        kwargs["temperature"] = settings.classifier_temperature
    return init_chat_model(chosen, **kwargs)


#: State flags that mean "this turn is a reply to something an agent showed".
CONTINUATION_FLAGS: tuple[str, ...] = ("widget_interaction", "game_result")

#: Where a continuation goes when the checkpoint has no active agent to resume.
#: The same list as `TEACHING_AGENTS`, and deliberately the same object, because
#: a continuation is always a reply to something a teaching agent showed.
CONTINUATION_FALLBACKS: tuple[str, ...] = TEACHING_AGENTS


def _continues_an_agent(state: AspireState, allowed: list[str]) -> str | None:
    """The agent this continuation belongs to, or None if it is not one."""
    flags = state.get("safety_flags") or {}
    if not any(flags.get(name) for name in CONTINUATION_FLAGS):
        return None

    active = state.get("active_agent")
    if active in allowed and active in CONTINUATION_FALLBACKS:
        return str(active)
    for fallback in CONTINUATION_FALLBACKS:
        if fallback in allowed:
            return fallback
    if active in allowed:
        return str(active)
    logger.warning(
        "A continuation arrived for session %s but neither %r nor any of %s is "
        "allowed; routing it normally.",
        state.get("session_id"),
        active,
        ", ".join(CONTINUATION_FALLBACKS),
    )
    return None


def make_classify(invoke=None):
    """Build the node."""

    async def classify(state: AspireState) -> dict[str, Any]:
        # `routable` drops `escalate_agent`.
        allowed = routable(list(state.get("allowed_agents") or []))
        if not allowed:
            # `guard` has already halted the turn; reaching here means the graph was wired wrong.
            return {"active_agent": None, "halt_reason": "access_denied"}

        active = state.get("active_agent")

        # ── a reply to something an agent showed, not a new question ──
        # A widget interaction or a game result resumes its agent instead of being routed.
        continuation = _continues_an_agent(state, allowed)
        if continuation is not None:
            return {
                "active_agent": continuation,
                "safety_flags": {
                    **(state.get("safety_flags") or {}),
                    "route": {
                        "agent": continuation,
                        "confidence": 1.0,
                        "reason": "continues the agent that showed the widget",
                    },
                },
            }

        if len(allowed) == 1:
            # No decision to make, and therefore no model call to pay for.
            return {
                "active_agent": allowed[0],
                "safety_flags": {
                    **(state.get("safety_flags") or {}),
                    "route": {"agent": allowed[0], "confidence": 1.0, "reason": "only option"},
                },
            }

        message = _latest_user_text(state)
        decision: Classification
        if invoke is None:
            decision = _coerce("", 0.0, "no classifier configured", state)
        else:
            user = (
                f"Handlers:\n{agent_menu(allowed)}\n\n"
                f"Currently handling: {active or 'nothing'}\n\n"
                f"Message: {message}"
            )
            try:
                raw = await invoke(_SYSTEM, user)
            except Exception:
                # A router outage must not be a product outage.
                logger.warning(
                    "Classifier call failed for session %s; falling back.",
                    state.get("session_id"),
                    exc_info=True,
                )
                raw = ""
            parsed = _parse(raw)
            if parsed is None:
                decision = _coerce("", 0.0, "unparseable", state)
            else:
                agent, confidence, reason, role = parsed
                decision = _coerce(agent, confidence, reason, state)
                if role:
                    # Carried even when the agent choice was coerced or made
                    # sticky: who is speaking is a separate question from which
                    # handler answers, and the reader said it either way.
                    decision = decision.model_copy(update={"role": role})

        decision = apply_stickiness(decision, state)

        # Belt and braces: this is the invariant the whole file exists to hold.
        if decision.agent not in allowed:  # pragma: no cover - unreachable by _coerce
            logger.error(
                "Classifier escaped the allowed list for session %s; forcing %s.",
                state.get("session_id"),
                allowed[0],
            )
            decision = Classification(agent=allowed[0], confidence=0.0, coerced=True)

        # The only record of a routing decision. Its ABSENCE is a signal too: the
        # continuation bypass and the single-option shortcut both return above this,
        # so no line means the router was never consulted.
        logger.info(
            "route session=%s agent=%s confidence=%.2f sticky=%s coerced=%s active=%s reason=%r",
            state.get("session_id"),
            decision.agent,
            decision.confidence,
            decision.sticky,
            decision.coerced,
            active,
            decision.reason,
        )

        _announce(state, decision.agent)
        return {
            "active_agent": decision.agent,
            "safety_flags": {
                **(state.get("safety_flags") or {}),
                "route": decision.model_dump(),
            },
        }

    return classify


def _announce(state: AspireState, agent: str) -> None:
    """Tell the stream interceptor which agent is about to run."""
    try:
        from langgraph.config import get_stream_writer

        get_stream_writer()(
            {
                "meta": {
                    "active_agent": agent,
                    "age_band": state.get("age_band", "5-8"),
                    "locale": state.get("locale", "en"),
                }
            }
        )
    except Exception:
        return


def _latest_user_text(state: AspireState) -> str:
    from app.graph.nodes.safety_in import latest_user_text

    return latest_user_text(state)


async def default_invoke(system: str, user: str) -> str:
    """The real model call, used when the graph is built for production."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.retry import with_retry

    model = _cached_model()
    response = await with_retry(
        lambda: model.ainvoke([SystemMessage(content=system), HumanMessage(content=user)]),
        what="classify.invoke",
    )
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


_model = None


def _cached_model():
    global _model
    if _model is None:
        _model = build_classifier_model()
    return _model
