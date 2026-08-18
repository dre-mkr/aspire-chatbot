"""Reading a message the way it was meant, not the way it was typed.

The model handles a typo perfectly well. The DETERMINISTIC gates in front of it
do not, and that is where casual input was being lost: `_small_talk_reply` in
`agents/qa/nodes.py` matches an anchored, closed list, so "hello" is answered
conversationally and "helo", "hiiiiii", "yo" and "hey there lol" fall straight
through it into retrieval -- where a greeting has no answer, scores nothing, and
comes back as a decline or an unrelated fact.

So this normalises for MATCHING only. The model always sees what the reader
actually wrote: it reads slang correctly, and rewriting the message before the
model would throw away tone the persona layer is entitled to notice.

Three rules, deliberately small:

1. Runs of three or more identical letters collapse to one. No word in English,
   Spanish or French carries a triple letter, so this cannot damage a real word,
   and it is what turns "hiiiiii" and "sooooo" into something matchable.
2. A closed table of everyday variants maps to its canonical word. Whole tokens
   only, so "yo" becomes a greeting and "yoghurt" does not.
3. Trailing laughter and filler is dropped -- "what even is aspire lol" is a
   question with a word stuck to the end of it.

None of this touches accents. "adiós" and "buenos días" are matched by patterns
that already spell both ways, and stripping them here would be a change to
Spanish and French behaviour made for the sake of English typing.
"""

from __future__ import annotations

import re
from typing import Final

#: Three or more of the same letter in a row.
_RUN: Final[re.Pattern[str]] = re.compile(r"(\w)\1{2,}", re.UNICODE)

#: Laughter and filler, when it is the whole of a token.
#:
#: Removed only at the EDGES of a message. "lol" in the middle of a sentence is
#: doing something -- "i said lol and she left" -- and a matcher that strips it
#: everywhere starts rewriting content rather than tidying it.
_FILLER: Final[frozenset[str]] = frozenset(
    {
        "lol",
        "lmao",
        "lmfao",
        "haha",
        "hahaha",
        "hehe",
        "hah",
        "xd",
        "rofl",
        "jaja",
        "jajaja",
        "mdr",
        "ptdr",
        "pls",
        "plz",
        "fr",
        "ngl",
        "tbh",
        "istg",
        "bruh",
        "bro",
        "fam",
        "innit",
    }
)

#: Everyday spellings that mean something already in a matcher's list.
#:
#: Whole-token replacements only. Every entry earns its place by being a thing a
#: reader actually types, and none of them is a word with another meaning in
#: English, Spanish or French that a reader would send on its own.
_VARIANTS: Final[dict[str, str]] = {
    # greetings
    "helo": "hello",
    "hallo": "hello",
    "hullo": "hello",
    "hii": "hi",
    "hiya": "hi",
    "heyy": "hey",
    "heya": "hey",
    "yo": "hi",
    "sup": "hello",
    "wassup": "hello",
    "wasup": "hello",
    "whatsup": "hello",
    "howdy": "hello",
    "greetings": "hello",
    "ola": "hola",
    "buenas": "hola",
    "slt": "salut",
    "bjr": "bonjour",
    # thanks
    "thx": "thanks",
    "thanx": "thanks",
    "tks": "thanks",
    "tysm": "thanks",
    "thankyou": "thank you",
    "gracias!": "gracias",
    "merci!": "merci",
    # acknowledgements
    "kk": "ok",
    "okk": "ok",
    "okey": "okay",
    "yh": "yes",
    "ya": "yes",
    "yup": "yes",
    "yeh": "yeah",
    "yea": "yeah",
    "nah": "no",
    "nope": "no",
    "np": "ok",
    "kool": "cool",
    "gotit": "got it",
    # farewells
    "cya": "bye",
    "byee": "bye",
    "laters": "bye",
    "ttyl": "bye",
    "adios": "adios",
}

_WORD: Final[re.Pattern[str]] = re.compile(r"[\w']+", re.UNICODE)


def squeeze_runs(text: str) -> str:
    """"hiiiiii" -> "hi". Doubles are left alone; they are ordinary spelling."""
    return _RUN.sub(r"\1", text)


def strip_filler(text: str) -> str:
    """Drop laughter and filler from the START and END of a message."""
    tokens = text.split()
    while tokens and _bare(tokens[0]) in _FILLER:
        tokens.pop(0)
    while tokens and _bare(tokens[-1]) in _FILLER:
        tokens.pop()
    return " ".join(tokens)


def _bare(token: str) -> str:
    """A token with its punctuation removed, for table lookups."""
    return re.sub(r"[^\w']", "", token, flags=re.UNICODE).lower()


def _map_tokens(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        canonical = _VARIANTS.get(word.lower())
        return canonical if canonical is not None else word

    return _WORD.sub(replace, text)


def casual_fold(text: str) -> str:
    """The message as it was meant, for matching against a closed list.

    Never use this as the text sent to the model, stored in the transcript, or
    shown back to the reader.
    """
    if not text:
        return ""
    squeezed = squeeze_runs(text)
    without_filler = strip_filler(squeezed)
    mapped = _map_tokens(without_filler)
    return re.sub(r"\s+", " ", mapped).strip()
