# ASPIRE experience pass — 14 client requests

2026-08-19 · branch `feat/aspire-experience-pass` · baseline `c477be3`

Fourteen items from the client brief. Nothing below says DONE without something
re-runnable behind it, and the four items that were **already built** say so
rather than claiming credit for them.

## What the brief asked for, measured against the tree

| # | Request | State found | What was done |
|---|---|---|---|
| 1 | Persona voices | **~80% built.** Per-persona voice ids and a per-persona delivery table both existed and were live. | Retuned to the brief; capped `style`; made every knob an env override. |
| 2 | Landing animation | **~30%.** Ambient blob drift existed and already paused in chat. No logo, no acronym, no arrow. | Brandmark, acronym, orbiting arrow, moving wash, stop-on-interaction. |
| 3 | Contextual video offer | 0% | Catalog, directive, two-tier relevance, offer-then-play. |
| 4 | Videos button + library | 0% | Rail launcher, panel, real-frame posters. |
| 5 | Automatic language | **~80% backend.** Detection already ran every turn. | Added the UI option, and made a manual pick able to clear a detected override. |
| 6 | Hangman | 0% | New game + an optional protocol for games whose submissions are moves. |
| 7 | Millionaire | **~5%, and a live bug.** The name was in four type unions with nothing behind it. | Built it; closed the bug. |
| 8 | Piggy bank | 0% | Progress indicator, coins, sound, reduced-motion behaviour. |
| 9 | True/False persona-aware | **Already built.** `engine.py` filters on `persona_bands`; seeds already split. | Content: 30 → 50 entries, and explanations that differ by band. |
| 10 | Scramble persona-aware | **Already built.** Same mechanism. | Content: 25 → 46 entries, two sets per tier. |
| 11 | Storytelling | 0% | Two-turn, user-initiated only. |
| 12 | Sources UI | Existed, plus a second dead renderer. | Redesigned the live one; deleted the dead one. |
| 13 | Persona everywhere | Largely true. | Sky/Zion rename; three duplicate name tables reduced to one. |
| 14 | Strictly additive | Constraint | One deletion, of unreachable code. See below. |

## The acronym

Quoted, never written:

> ASPIRE — Achieving Success through Personal Investment, Resources and Education

Source: `backend/data/knowledge_base.csv` row `ASP-002`, attributed to
`https://aspire.gov.kn/`. It now lives in one exported constant
(`Brandmark.tsx`) so the landing page and the sign-in surface cannot drift.

## Bugs found on the way

These were not on the list. Each was found by driving the running app rather
than by a test, and each would have shipped.

**A card intent missing from the cache guard disables its whole feature.**
The layer-1 response cache answers before the graph runs, so a message
`_wants_card` does not recognise is served from somebody else's answer and the
card node never executes — meaning any state it would have set is never set.
`awaiting_story_topic` was therefore written once per process and never again;
every later reader was asked for a topic and had it answered as an ordinary
question. Video acceptance failed identically. Found by reading the network
trace: `"agent":"cache"`.

**Millionaire was a name with nothing behind it.** It appeared in
`directives.py`, `intents.py`, the frontend directive union and the learn
agent's engine map. Four separate two-way branches decided which game was
which, and every one fell through to the word scramble — so a named game with
no implementation became a *different game* rather than an error. They now read
one table.

**A story for the youngest readers would have been cut at 35 words.**
`cap_for` knew about lessons and Q&A and gave everything else the plain chat
ceiling. `truncate_at_sentence` does it silently; the build and the tests stay
green and a child gets half a story.

**Two right answers running dropped one coin.** An effect on `mood` fires when
the value changes, and "fed" over "fed" is not a change. Right-then-wrong
animated; right-then-right did not.

**The new games reached the "which game?" chips as raw wire ids** — "hangman"
beside "True or false". The existing tests caught this one.

## A trap in the seed content, for whoever expands it next

`tests/games/test_no_answer_leak.py` builds its forbidden list from **every**
seeded scramble answer and checks the served payload against all of them. So
seeding an ordinary word turns somebody else's clue into a leak, in a file you
did not touch.

`NEED` did exactly that: the ECCB warm-up handout has defined MONEY as *"what we
use to buy the things we need"* since the first commit, and that file is the
printed source, so `NEED` was the side that had to give. The note is now at the
top of the bank that tried it.

I also wrote the general version of that test — no answer in any other item's
clue — ran it, and deleted it. It fails on the original handout in eleven
places, because defining INTEREST requires saying "bank" and defining SAVE
requires saying "money". The invariant the suite states is not one this
vocabulary can satisfy; it holds today only because the leak tests exercise one
entry of one set. A test that fails on the client's own authoritative content is
one the next person deletes, so it was better not to add it.

## Content grounding

No ASPIRE fact in any new game seed was written from memory. Each traces to a
corpus row, cited in `source_document`:

| Claim | Row |
|---|---|
| EC$1,000 split EC$500 savings / EC$500 shares | `ASP-012`, `ASP-013` |
| 2.0% minimum savings rate is an ECCB floor | `FIN-038`, `FIN-039` |
| 10-20-30-40: debt payments never exceed 40% | `FIN-346` |
| Dividends automatically reinvested | `ASP-090`, `ASP-091` |
| Rule of 72 — 6% ≈ 12 years | `FIN-127` |

An adversarial pass over the drafted seeds rejected, among others: *"eight
Eastern Caribbean **countries** share one of these"* (the corpus says
*members*; Anguilla and Montserrat are British Overseas Territories);
insurance as *"the only one you buy"* of the four ways of handling risk
(contradicted by the cited row's own example — a helmet is bought, and it is
the *reduce* arm); a distractor truncated to *"All of it sits in a savings
account until the participant completes"*; and hints referring to "all eight
words" when a round serves four.

## The one deletion

`DirectiveRegistry.Citations` and its dispatch. It was unreachable —
`stream.ts` intercepts `t === "citations"` and returns before the directive is
ever pushed — so two divergent sources UIs existed and only one could render.
No user-visible behaviour was removed.

## One architectural change, and why

`Game` assumed one submission settles one item. That is true of a scramble and
of a true/false and is not true of hangman: a letter is a move, not a verdict,
and under the old rule the first correct letter ended the word.

`GameWithMoves` is an **optional** protocol, checked with `isinstance` at one
point in `GameEngine.submit`, so no existing game is affected. A game that has
moves keeps its per-item state in a scratchpad on the session and says when the
item is finished. The board is still built forward from the letters *earned*,
never from the word with letters removed, so nothing on the wire can be read
back into the answer.

## What still needs the client

**Voice ids.** ElevenLabs has no accent parameter and the code never sends
`language_code`, so the only thing that makes a voice sound Caribbean is which
voice id is chosen. The delivery table is tuned and every knob is now an env
override; `backend/.env.example` carries the character brief per persona and
the rule that matters — never trade intelligibility for an accent. Choosing the
ids needs the client's account and a human ear.

**Re-prewarm the voice cache.** The cache is keyed on all four delivery knobs,
so the tuning invalidates it. Run `tests/scripts/prewarm_voice.py`; it spends
ElevenLabs credit, so run it deliberately.

**Git LFS on every checkout.** The two films are ~185MB and Monique's is over
GitHub's 100MB single-file limit, so LFS is not a preference. A clone without
`git lfs install` leaves 130-byte pointer files and the panel serves those
instead of video. A test asserts each catalog entry names a file that is really
an MP4, so this fails loudly rather than silently.

**Spanish and French video tracks.** Both films are English, so `relevant_to`
declines to offer one to a reader in another language rather than offering a
wall. One line changes when tracks exist.

## Verification

```
cd backend && .venv/Scripts/python.exe -m pytest -q -m "not slow"
cd frontend && npx tsc --noEmit
cd frontend && VITE_ASPIRE_API_URL=https://aspire.eccugenai.app npx vite build
```

`-m "not slow"` matters locally: `backend/.env` carries an OpenAI key, so the
slow-marked tests are **not** skipped here and make roughly 200 real gpt-4o
calls.

Driven in the browser rather than only asserted: the videos panel and inline
player, the offer-then-play flow, the brandmark orbit (stepped by hand — a
hidden tab does not composite, so nothing advances on its own), the language
selector, Hangman letter by letter, Millionaire with the piggy bank, and the
story flow end to end.
