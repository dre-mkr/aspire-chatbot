"""The third outcome: saying we do not know, usefully.

Before this, a QA turn had two endings -- a grounded answer, or a person. Four
of the nine escalation reasons were retrieval failures, and they produced 23 of
58 live tickets. Every one of those was the assistant meeting the edge of its
corpus and fetching a human to say so.

A decline is what belongs between them, and it has three parts, in this order:

  1. **What we do know.** The nearest thing the corpus actually holds, named
     rather than quoted. Skipped entirely when retrieval returned nothing --
     inventing a partial answer to soften a decline is the failure mode this
     product least wants.
  2. **Who holds the rest.** Named specifically, because "contact us" is a
     decline wearing a helpful hat. The ASPIRE team, the website, a branch.
  3. **A question we CAN answer.** Taken from a retrieved row's own title, so
     the offer is guaranteed answerable -- an offer that leads back to another
     decline is worse than no offer.

## No model call

Every string here is authored and band-aware, for the same reasons the hint
ladder and the registration prompts are: a generated decline is a different
decline every time, it is one more place a banned word can enter, and it costs a
second round trip on a turn that has already spent one on a generation nobody
will read.

## It is not an apology

"I'm sorry, I don't have that information" invites the reader to try again in
different words, which is exactly the loop the counter exists to catch. The copy
below states the boundary and moves.
"""

from __future__ import annotations

from typing import Any

from app.graph.state import AspireState, KBChunk

#: How the decline opens, by band. The youngest bands get the shortest form and
#: no institutional vocabulary -- "the ASPIRE team" means nothing to a
#: six-year-old, so for them the offer of a person is the whole of part 2.
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

#: Part 2 -- who holds the rest. Children are pointed at a person, not a
#: website: `safety_out` strips links for them anyway, and a URL is not an
#: instruction a nine-year-old can act on alone.
_WHO_HOLDS_IT: dict[str, dict[str, str]] = {
    "en": {
        "child": "Ask a grown-up to check with the ASPIRE team.",
        "adult": "The ASPIRE team can answer it — aspire.gov.kn, or any branch.",
    },
    "es": {
        "child": "Pide a una persona mayor que consulte al equipo de ASPIRE.",
        "adult": "El equipo de ASPIRE puede responder — aspire.gov.kn, o una sucursal.",
    },
    "fr": {
        "child": "Demande à un adulte de contacter l'équipe ASPIRE.",
        "adult": "L'équipe ASPIRE peut répondre — aspire.gov.kn, ou une agence.",
    },
}

#: Part 3 -- the offer.
#:
#: The topic is a corpus row's own title, and those are written AS QUESTIONS
#: ("Can a parent withdraw the child's savings?"). So the template quotes it
#: rather than embedding it after a preposition -- "I can tell you about can a
#: parent withdraw the child's savings" is what the first draft produced.
_OFFER: dict[str, str] = {
    "en": 'You could ask me this one instead: "{topic}"',
    "es": 'Puedes preguntarme esto: "{topic}"',
    "fr": 'Tu peux me demander ceci : "{topic}"',
}

_CHILD_BANDS = frozenset({"5-8", "9-12"})


def _band(state: AspireState) -> str:
    return str(state.get("age_band") or "adult")


def _locale(state: AspireState) -> str:
    locale = str(state.get("locale") or "en")
    return locale if locale in _OPENING else "en"


def nearest_topic(chunks: list[KBChunk]) -> str | None:
    """A topic the corpus can actually answer, from the best chunk's own title.

    The title rather than the content, because a title is already a question
    somebody wrote on purpose ("Who registers a child for ASPIRE?") and is
    therefore guaranteed to have an answer behind it. Content would give a
    fragment that may or may not correspond to anything askable.

    Returned VERBATIM, question mark and capital included, because the offer
    template quotes it back as a question the reader can literally send.

    Returns None when nothing was retrieved, or when the best chunk has no
    title -- and the caller then omits part 3 rather than inventing a topic.
    """
    for chunk in chunks:
        title = (chunk.title or "").strip()
        if title:
            return title
    return None


def decline_text(state: AspireState, chunks: list[KBChunk]) -> str:
    """The three-part decline, assembled for this reader."""
    locale, band = _locale(state), _band(state)
    audience = "child" if band in _CHILD_BANDS else "adult"

    parts = [
        _OPENING[locale].get(band, _OPENING[locale]["adult"]),
        _WHO_HOLDS_IT[locale][audience],
    ]

    topic = nearest_topic(chunks)
    if topic:
        parts.append(_OFFER[locale].format(topic=topic))

    return " ".join(parts)


def decline_chips(state: AspireState, chunks: list[KBChunk]) -> list[str]:
    """Chips under a decline. At most one, and only if it leads somewhere real.

    Deliberately not "try again" or "rephrase". Inviting a rephrase is inviting
    the loop the counter exists to catch, and a chip that leads back to a second
    decline teaches the reader the assistant is broken rather than bounded.
    """
    topic = nearest_topic(chunks)
    if not topic:
        return []
    words = topic.rstrip("?").split()
    return [" ".join(words[:4])]


def decline_update(state: AspireState, chunks: list[KBChunk]) -> dict[str, Any]:
    """The state update for a declined turn, minus the streak.

    The caller owns the streak because the caller knows the question text the
    streak is keyed on.
    """
    from langchain_core.messages import AIMessage

    return {
        "messages": [AIMessage(content=decline_text(state, chunks))],
        "quick_replies": decline_chips(state, chunks),
        # A decline cites nothing. It is the absence of an attributable answer,
        # and attaching the chunks that failed the floor would render sources
        # under a message that is not sourced from them.
        "citations": [],
        "groundedness": 0.0,
    }
