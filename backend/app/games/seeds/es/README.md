# Spanish word sets — to be authored

**Empty on purpose. Do not fill this by translating the English set.**

A scramble is a puzzle about a specific string of letters. MONEY, DINERO and
ARGENT are three different letter sets, so an English scramble carries no
information about the Spanish word — `NOEYM` does not unscramble to `DINERO`,
and no amount of translation makes it.

Running the English set through a translator would produce entries whose
`scramble` is not an anagram of their `word`. The seed-integrity test fails the
build on exactly that, which is the intended outcome.

## What is needed instead

A Spanish speaker authors the words, the scrambles, the hints and the
definitions natively, at roughly a grade-2 reading level, using the vocabulary
ASPIRE actually uses in Spanish. Then drop a file here shaped like
`../en/warmup-01.yaml`, with `language: es` on the set and on every entry.

The loader picks up any `*.yaml` in this folder automatically. Nothing in the
engine, the tools or the agent needs to change.

## Until then

`start_game(language="es")` declines with `no_set_for_language`, and the
assistant explains that the game is only ready in English so far. That is the
correct behaviour — a wrong puzzle is worse than no puzzle.
