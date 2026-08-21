"""The one place an agent's message list is built."""

from __future__ import annotations

from typing import Any, Iterable

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.context.session_context import SessionContext
from app.prompting.global_rules import GLOBAL
from app.prompting.personas import persona_card

#: What the retrieved block is introduced with, in the human turn.
_CONTEXT_HEADING = "Reference material for this question:"

#: What the history block is introduced with.
_HISTORY_HEADING = "The conversation so far:"

#: Named rather than coded, because "es" is a string and Spanish is a language.
_LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "fr": "French"}
_SUMMARY_HEADING = "Earlier in this conversation:"


def _contact_block() -> str:
    """ASPIRE's own details, so "offer them" is an instruction that can be followed.

    `GLOBAL` tells the model to offer ASPIRE's contact details for the final
    word and, two lines earlier, never to invent a contact detail. Both are
    load-bearing and neither was satisfiable: nothing anywhere in the composed
    prompt said what the details ARE. A per-deployment fact rather than a rule,
    so it sits beside the rules instead of inside them.
    """
    from app.agents.escalation.decline import contacts

    details = contacts()
    return (
        "ASPIRE'S OWN CONTACT DETAILS\n"
        "These, exactly as written, are the only ones. Never offer any other, "
        "and never adapt these.\n"
        f"- Email: {details['email']}\n"
        f"- Phone: {details['phone']}\n"
        f"- Phone (second line): {details['phone_alt']}\n"
        f"- Website: {details['website']}\n"
        f"- In person: {details['office']}"
    )


#: What a card's runtime placeholders are written as.
#:
#: `{name}` is filled in by `persona_card` and is not here: a label belongs to a
#: persona and changes with a client's taste. These four belong to a deployment
#: and to a conversation, and the cards quote them inside the escalation script
#: the reader is actually read out -- "email {email} or call {phone}". Written
#: out rather than left literal for the same reason the contact block exists at
#: all: two places saying a phone number is one place saying it wrong.
_CARD_FIELDS = ("email", "phone", "phone2", "ref")

#: What `{ref}` becomes when there is no session to derive one from.
#:
#: A phrase rather than an empty string, because the sentence around it is read
#: aloud: "Tell them so they know we talked" is a sentence with a hole in it,
#: and a dangling `ASP-` is worse.
_NO_REFERENCE = "your conversation reference"


def _fill_card(card: str, context: SessionContext) -> str:
    """A persona card with this deployment's contacts and this session's reference."""
    from app.agents.escalation.decline import contacts

    details = contacts()
    values = {
        "email": details["email"],
        "phone": details["phone"],
        "phone2": details["phone_alt"],
        "ref": context.conversation_ref or _NO_REFERENCE,
    }
    # `str.replace`, not `str.format`, for the reason `persona_card` gives: a
    # card is prose, and a brace in it would raise in front of a reader.
    for field in _CARD_FIELDS:
        card = card.replace("{" + field + "}", values[field])
    return card


def stable_prefix(context: SessionContext, agent_role: str) -> str:
    """The three layers that must not change within a session."""
    return "\n\n".join(
        part.strip()
        for part in (
            GLOBAL,
            _contact_block(),
            _fill_card(persona_card(context.persona, context.age_band), context),
            agent_role,
        )
        if part and part.strip()
    )


def _turn_context(context: SessionContext) -> str:
    """The per-turn system block: summary, then history verbatim."""
    blocks: list[str] = []
    if context.running_summary.strip():
        blocks.append(f"{_SUMMARY_HEADING}\n{context.running_summary.strip()}")
    if context.recent_turns:
        lines = "\n".join(f"{turn.role}: {turn.text}" for turn in context.recent_turns)
        blocks.append(f"{_HISTORY_HEADING}\n{lines}")

    # Facts the reader should not have to repeat.
    #
    # The band and the language were both carried on `SessionContext` and
    # neither was ever written into a message: the reader's age reached the
    # model only by implication, through which persona card got composed, and
    # the language not at all. So the band was stated to the model for the first
    # time in `safety_out`'s re-prompt -- after it had already written past the
    # cap -- and the language likewise, after it had already answered in the
    # wrong one. Both are cheaper said once, up front.
    facts = [f"Today is {context.now.strftime('%A %d %B %Y')}."]
    facts.append(f"You are writing for a reader in the {context.age_band} age band.")
    facts.append(f"This conversation is in {_LANGUAGE_NAMES.get(context.locale, context.locale)}.")
    if context.display_name:
        facts.append(f"You are speaking with {context.display_name}.")
    blocks.append(" ".join(facts))

    return "\n\n".join(blocks)


def _retrieved_block(chunks: Iterable[Any]) -> str:
    """Retrieved rows, formatted for the human turn.

    Each row arrives carrying the CSV's bookkeeping columns -- `keywords`,
    `audience`, `as_of` and, most of all, `source_url`. `without_provenance`
    takes them off. The model is asked to cite by `[ASP-xxx]` id and never to
    write a URL, and it was being shown one per extract; the citation panel is
    built from the metadata the application kept, not from anything the model
    can read here.
    """
    from app.sources import without_provenance

    lines = [
        f"[{getattr(chunk, 'kb_id', '?')}] {body}"
        for chunk in chunks
        if (body := without_provenance(getattr(chunk, "content", "") or ""))
    ]
    return f"{_CONTEXT_HEADING}\n" + "\n\n".join(lines) if lines else ""


def build_messages(
    *,
    context: SessionContext,
    agent_role: str,
    user_text: str,
    retrieved: Iterable[Any] = (),
    extra_instruction: str | None = None,
) -> list[BaseMessage]:
    """The message list for one agent call."""
    messages: list[BaseMessage] = [SystemMessage(content=stable_prefix(context, agent_role))]

    turn_context = _turn_context(context)
    if extra_instruction and extra_instruction.strip():
        turn_context = f"{turn_context}\n\n{extra_instruction.strip()}".strip()
    if turn_context:
        messages.append(SystemMessage(content=turn_context))

    human = user_text.strip()
    retrieved_block = _retrieved_block(retrieved)
    if retrieved_block:
        human = f"{human}\n\n{retrieved_block}" if human else retrieved_block
    messages.append(HumanMessage(content=human))

    return messages
