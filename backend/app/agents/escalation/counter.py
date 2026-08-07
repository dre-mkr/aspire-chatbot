"""Three unresolved turns on one intent, and only then a person.

The one counter in the system, and the only thing permitted to produce
`REPEATED_FAILURE`. Everything in `contract.IMMEDIATE` bypasses it entirely --
a child asking for help does not ask three times.

## What "consecutive on the same intent" means here

Literally that. The streak is a single `{intent: count}` entry, not a tally per
topic, because the moment the intent changes the previous run is over. Asking
about eligibility twice, then about deadlines, then about eligibility again is
one-then-one, not three: the person moved on and came back, which is browsing,
not a person stuck in a loop.

Modelling it as a dict rather than an `(intent, count)` pair costs nothing and
makes the state readable in a checkpoint dump -- you can see WHICH intent
somebody is stuck on, which is the thing worth knowing when this fires.

## Why the checkpoint is a safe home for it

The counter is an integer and a normalised question fragment. No PII, no
identity, nothing that outlives the session it belongs to. It rides in
`AspireState` and is therefore per-thread, which is per-session, which is the
scope the specification asks for -- so "keyed on session+intent" needs no
session component in the key; the checkpoint IS the session.

## `CLARIFICATION_LIMIT` was already here, and dead

`agents/escalate/graph.py:89` declared the number 3 with a comment describing
this exact rule, and nothing read it. The diagnosis found it by grep. This wires
it up rather than declaring a second constant beside it.
"""

from __future__ import annotations

import re
from typing import Final

from app.agents.escalation.contract import EscalationReason

#: Consecutive unresolved turns on one intent before a person is fetched.
#: Imported from where it was already written, so there is one number.
from app.agents.escalate.graph import CLARIFICATION_LIMIT as LIMIT  # noqa: E402

__all__ = ["LIMIT", "intent_key", "bump", "clear", "at_limit", "escalation_for"]

_WORD = re.compile(r"[a-z0-9']+")

#: Words that carry no topic. Two questions differing only in these are the same
#: question asked twice, which is exactly the case the counter exists for.
_STOP: Final[frozenset[str]] = frozenset(
    """
    a an the is are was were do does did can could would should will shall may
    might i you he she it we they me my your our their this that these those
    to of for from with about on in at by and or but if so what which who whom
    whose when where why how please tell me know want need get give show
    """.split()
)


def intent_key(text: str, *, keep: int = 6) -> str:
    """A stable, coarse key for "the same thing, asked again".

    Content words only, sorted, capped.

    Sorting handles REORDERING: "what documents do I need" and "I need what
    documents" are one intent. It does not handle REWORDING -- "what documents
    do I need" keys as `documents`, and "what documents for my child" keys as
    `child documents`, which resets the streak. That is a real limitation and
    it fails in the safe direction: the counter under-fires, so somebody who
    rephrases substantially gets more attempts before a person is fetched,
    rather than fewer. Given this whole track exists because escalation fired
    too readily, under-firing is the error to prefer.

    Coarse on purpose otherwise. A key fine enough to separate every genuinely
    different question is also fine enough to never fire twice on anything,
    which is the state this replaces.
    """
    words = [word for word in _WORD.findall((text or "").lower()) if word not in _STOP]
    return " ".join(sorted(words)[:keep])


def bump(streaks: dict[str, int] | None, text: str) -> dict[str, int]:
    """The streak after one more unresolved turn.

    Returns a single-entry dict. Anything previously tracked is dropped, which
    IS the "reset on intent change" rule -- there is no second entry to reset.
    """
    key = intent_key(text)
    if not key:
        # Nothing to key on ("?", an emoji). Not a repeat of anything, and not
        # something to start a streak with either.
        return {}
    current = (streaks or {}).get(key, 0)
    return {key: current + 1}


def clear(streaks: dict[str, int] | None = None) -> dict[str, int]:
    """The streak after a resolved turn. Empty, always.

    Called on every successful answer. A person who got what they asked for is
    not two-thirds of the way to needing a human, even if the next two questions
    happen to fail.
    """
    return {}


def at_limit(streaks: dict[str, int] | None, text: str) -> bool:
    """Whether this intent has now failed `LIMIT` times in a row."""
    return (streaks or {}).get(intent_key(text), 0) >= LIMIT


def escalation_for(streaks: dict[str, int] | None, text: str) -> EscalationReason | None:
    """`REPEATED_FAILURE` if the streak has run out, else None.

    The only function in the codebase that may return `REPEATED_FAILURE`, so
    that "how does a turn earn a human?" has one answer with one line number.
    """
    return EscalationReason.REPEATED_FAILURE if at_limit(streaks, text) else None
