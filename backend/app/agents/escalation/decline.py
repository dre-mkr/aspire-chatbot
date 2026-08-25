"""The third outcome: saying we do not know, usefully."""

from __future__ import annotations

import re

from typing import Any

from app.graph.state import AspireState, KBChunk

#: How the decline opens, by band.
_OPENING: dict[str, dict[str, str]] = {
    "en": {
        "5-8": "I do not know that one!",
        "9-12": "I do not have that one.",
        "13-15": "I do not have an answer for that.",
        "16-18": "I do not have an answer for that.",
        "adult": "I do not have an answer for that.",
    },
    "es": {
        "5-8": "¡Esa no me la sé!",
        "9-12": "Esa no la tengo.",
        "13-15": "No tengo una respuesta para eso.",
        "16-18": "No tengo una respuesta para eso.",
        "adult": "No tengo una respuesta para eso.",
    },
    "fr": {
        "5-8": "Celle-là, je ne la sais pas !",
        "9-12": "Je ne l'ai pas.",
        "13-15": "Je n'ai pas de réponse à cela.",
        "16-18": "Je n'ai pas de réponse à cela.",
        "adult": "Je n'ai pas de réponse à cela.",
    },
}

#: Part 2 -- who holds the rest, and how to reach them.
#
#: The global prompt has always told the model to offer ASPIRE's contact details
#: and never to invent one, and never supplied any -- so this was the whole of
#: the answer to "who does know?": a domain name. `{email}`, `{phone}` and
#: `{website}` come from config, defaulted to what the corpus already publishes.
#:
#: A child's line is UNCHANGED and carries no channel at all. That is a
#: deliberate decision with a test naming it -- `a_child_is_pointed_at_a_grown_
#: _up_not_a_website` -- and a first draft of this change broke it. The reasoning
#: holds: handing a nine-year-old a phone number routes them around the adult
#: who is supposed to be between them and the programme.
_WHO_HOLDS_IT: dict[str, dict[str, str]] = {
    "en": {
        "child": "Ask a grown-up to check with the ASPIRE team.",
        "adult": "The ASPIRE team can answer it — {email}, {phone}, or {website}.",
    },
    "es": {
        "child": "Pide a una persona mayor que consulte al equipo de ASPIRE.",
        "adult": "El equipo de ASPIRE puede responder — {email}, {phone}, o {website}.",
    },
    "fr": {
        "child": "Demande à un adulte de contacter l'équipe ASPIRE.",
        "adult": "L'équipe ASPIRE peut répondre — {email}, {phone}, ou {website}.",
    },
}


def contacts() -> dict[str, str]:
    """ASPIRE's own details, for a template to fill in."""
    from app.config import get_settings

    settings = get_settings()
    return {
        "email": settings.aspire_contact_email,
        "phone": settings.aspire_contact_phone,
        "phone_alt": settings.aspire_contact_phone_alt,
        "website": settings.aspire_contact_website,
        "office": settings.aspire_contact_office,
    }

#: Part 3 -- the offer.
_OFFER: dict[str, str] = {
    "en": 'You could ask me this one instead: "{topic}"',
    "es": 'Puedes preguntarme esto: "{topic}"',
    "fr": 'Tu peux me demander ceci : "{topic}"',
}

_CHILD_BANDS = frozenset({"5-8", "9-12"})

#: The longest a decline chip may be before it is dropped instead of cut.
#: Matches the widest label the existing chips already ship -- "Can I withdraw
#: funds from the ASPIRE savings account?" is 52 characters and renders fine.
_MAX_CHIP_CHARS = 64


def _band(state: AspireState) -> str:
    return str(state.get("age_band") or "adult")


def _locale(state: AspireState) -> str:
    """The language to decline in: what they WROTE, then what the session says.

    The session's locale comes from the token, and a reader who switches
    language mid-thread does not re-mint one -- so someone who asked in French
    was declined in English, inside a conversation the model was otherwise
    answering in French. Once the decline replaced the answer rather than
    trailing it, that stopped being a blemish and became the whole reply.

    `detect_locale` needs about eight words and a clear margin, and returns
    None when it cannot tell. That is the right shape here: an override when
    the evidence is good, and the session's own answer when it is not.
    """
    from app.graph.nodes.safety_in import latest_user_text
    from app.graph.nodes.safety_out import detect_locale

    written = detect_locale(latest_user_text(state) or "")
    if written in _OPENING:
        return str(written)

    locale = str(state.get("locale") or "en")
    return locale if locale in _OPENING else "en"


def _writes_as_child(state: AspireState) -> bool:
    """Whether to point this reader at a grown-up rather than at a channel.

    A child band we ESTABLISHED, not one we defaulted to. A signed-out visitor
    bands as the youngest because an unknown age has to read as the youngest --
    but the band then also decided the routing, so the most likely reader of a
    decline, a parent looking the programme up before signing anyone up, was
    told to go and ask a grown-up.

    The reading level is unaffected: caps, vocabulary and link stripping still
    treat an unproven reader as the youngest. Only "who does know" changes.
    """
    if _band(state) not in _CHILD_BANDS:
        return False
    return bool(state.get("identity_proven"))


#: Words too common to tell two questions apart.
_STOPWORDS: frozenset[str] = frozenset(
    "a an the of to for do does did i my me you your is are was what which how "
    "que el la los las un una de del para por mi yo tu es son como cual cuales "
    "le les des du un une pour par mon ton est sont comme quel quelle".split()
)


def _shape(text: str) -> frozenset[str]:
    """The content words of a question, for comparing two of them."""
    words = re.findall(r"[^\W\d_]+", (text or "").casefold(), re.UNICODE)
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 2)


def _too_alike(topic: str, asked: str) -> bool:
    """Whether the offer is the question that was just declined.

    Observed on production, 25 Aug: "what documents do i need" was declined
    with 'You could ask me this one instead: "What documents do I need to
    register?"'. The offer is the whole value of a decline -- it is the one
    part that gives the reader somewhere to go -- and handing back their own
    sentence reads as a fault they caused. Their words are dropped from the
    comparison, so this catches a rewording as well as a repeat.
    """
    a, b = _shape(topic), _shape(asked)
    if not a or not b:
        return False
    return a <= b or b <= a


def _asked(state: AspireState) -> str:
    """The reader's own last message, for keeping the offer off it."""
    for message in reversed(list(state.get("messages") or [])):
        if getattr(message, "type", "") == "human":
            content = getattr(message, "content", "")
            return content if isinstance(content, str) else ""
    return ""


def nearest_topic(chunks: list[KBChunk], asked: str = "") -> str | None:
    """A topic the corpus can answer, from the best chunk's own title.

    `asked` is the reader's own question, and a title that merely restates it
    is skipped in favour of the next chunk's.
    """
    for chunk in chunks:
        title = (chunk.title or "").strip()
        if title and not _too_alike(title, asked):
            return title
    return None


def decline_text(state: AspireState, chunks: list[KBChunk]) -> str:
    """The three-part decline, assembled for this reader."""
    locale = _locale(state)
    as_child = _writes_as_child(state)
    # The opening follows the audience too, not the raw band. Split the two and
    # an unproven reader got "I do not know that one!" -- the five-to-eight line
    # -- followed by an email address and a phone number. Measured, and it reads
    # exactly as mismatched as it sounds.
    band = _band(state) if as_child else "adult"
    audience = "child" if as_child else "adult"

    parts = [
        _OPENING[locale].get(band, _OPENING[locale]["adult"]),
        _WHO_HOLDS_IT[locale][audience].format(**contacts()),
    ]

    topic = nearest_topic(chunks, _asked(state))
    if topic:
        parts.append(_OFFER[locale].format(topic=topic))

    return " ".join(parts)


def decline_chips(state: AspireState, chunks: list[KBChunk]) -> list[str]:
    """Chips under a decline.

    THE CHIP IS THE OFFER, so it has to be tappable. This used to return the
    first four words of the topic, which produced labels like "What is the best"
    and "What is a contingency" -- observed on production, 23 August 2026, under
    a decline whose own prose had just quoted the whole question in full. The
    reader saw the complete question and then a fragment of it on the button.

    That is the failure `chips_within_band` already describes for a chip with a
    banned word cut out of it: "I think a" is not an option anybody can tap, and
    offering it is worse than offering one fewer. Truncating for length produces
    exactly the same unusable thing for a different reason.

    So the topic goes on the chip WHOLE, with its question mark, and a topic too
    long to fit is dropped rather than cut. `_chip` in the stream layer already
    shortens at a word boundary for display; what it must never be handed is a
    label that has stopped being a question.
    """
    topic = nearest_topic(chunks, _asked(state))
    if not topic:
        return []
    label = topic.strip()
    if not label:
        return []
    if not label.endswith("?"):
        label = label.rstrip(".") + "?"
    # Longer than a chip can carry: no label at all beats half a question.
    if len(label) > _MAX_CHIP_CHARS:
        return []
    return [label]


def decline_update(state: AspireState, chunks: list[KBChunk]) -> dict[str, Any]:
    """The state update for a declined turn, minus the streak."""
    from langchain_core.messages import AIMessage

    return {
        "messages": [AIMessage(content=decline_text(state, chunks))],
        "quick_replies": decline_chips(state, chunks),
        # A decline cites nothing.
        "citations": [],
        "groundedness": 0.0,
    }
