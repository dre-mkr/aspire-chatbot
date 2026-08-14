# Phases 0 and 1

2026-08-14 · branch `fix/judging-readiness` · baseline tag `pre-judging-fixes` (`2c8e529`)

Recon, the judging harness, observability, and the four safety criticals. Twelve
commits. The map of where everything lives is `qa-defect-map.md`; this is what
changed and what it cost.

---

## What the numbers did

| | before | after |
|---|---|---|
| judging suite (signed out, 13 cases) | 8/12 | **10/13** |
| turns delivering a spurious decline | **7 of 27** | 2 of 27, both legitimate |
| declines by cause | 5 floor, 1 figure, 1 uncited | 1 floor, 1 figure |
| safeguarding languages heard | 1 of 3 | **3 of 3** |
| anonymous session's band | `aurora` / adult | `stella` / 5-8 |
| voice endpoints open to anybody | 3 | **0** |
| chat turns emitting a timing line | 0 | all |

Latency, first measurement of any kind on this path: `t_ttft` p50 **7.9s** /
p95 11.4s, `t_total` p50 **10.2s** / p95 13.6s, over 30 golden questions with
the answer cache flushed. The brief said 20-28s. It is not that, but it is not
under ten either.

---

## The one that was not in the brief

26% of turns delivered a correct, cited answer with an English decline welded
onto the end, no separating space:

```
...Saving for a bigger goal is one reason to save.I do not have an answer for
that. The ASPIRE team can answer it -- aspire.gov.kn, or any branch.
```

The QA report saw this in Spanish and filed it as a translation defect. It is
not: it happens in English too, and the same shape reached a French answer. Two
faults meet.

`ground_check` runs after `generate` has streamed, so a decline can only follow
the answer, never replace it. And the relevance floor scores RETRIEVAL, while
the checks below it -- `uncited`, `invented_citation`, `unattributed_figure` --
measure whether the ANSWER is grounded. Ordered floors-first, the stand-in
overruled the evidence. Five of seven declines were scores of 0.457-0.542
against a 0.550 floor, every one carrying citations. One was "what is my
daughter's name", answered correctly out of the conversation -- not a corpus
question at all, and it can never score against the corpus.

The floors now read the citation set first, and the dense one splits: below a
hard floor nothing is served, between the two the evidence decides. That shape
was forced by two existing tests, and they were right to. A plain "cited, so
serve it" made *"how do I renew a fishing licence"* -> *"At the fisheries office
[ASP-006]"* servable, because citing a retrieved id proves nothing about where
the words came from.

The welding itself is T3.1's, and it is what cases 9 and 10 still catch.

---

## Phase 1

**T1.1 — an unknown age is a child.** Two paths read "we were not told" as
"adult". Measured on the database rather than argued: 30,327 anonymous rows and
**148 registered participants** carry no date of birth and were banded adult --
no word caps, no vocabulary rules, links left in. A participant is eighteen or
under by definition, so for those 148 adult was not merely unsafe, it was wrong.
No guardian or educator row has a null date of birth, so no adult-facing account
regresses. The picker stays open: a parent may still choose Aurora, and the
safety is in the default.

**T1.2 — distress in three languages.** `quiero morirme` and `je veux mourir`
both returned `None` and went to the router to be answered as ordinary
questions. The most serious thing the 13 Aug run turned up and the least visible
from outside, because nothing errors. Fixed, and folded before matching so a
reader who does not type their accents is still heard. The first draft was
dangerous in the other direction -- `me toca` is also "it is my turn", so
*"¿Cuánto me toca ahorrar?"* raised a safeguarding ticket and notified a
guardian -- and eight negative cases now hold that line.

**T1.3 — the body is not a source of claims.** `session_id` and `device_id` went
unread from the request body into the signed token, and `sid` then served as the
thread id, the conversation id and the rate-limit key. 1,998 of 3,779
conversations have no owner and 56 have an id under thirty characters. Not a
UUID requirement: `newThreadId` falls back to `t-<base36>-<base36>` on an older
Safari, which is a fair description of this audience.

**T1.4 — voice.** Three endpoints open to anybody, metered on a thread id the
caller supplied, with the cache short-circuit sitting above the limiter so a
warm line was free forever. Verified live: all three 401 without a session, and
`/speak` with a real anonymous token returns 200 `audio/mpeg`.

---

## Two things I got wrong, and how they surfaced

**A whole baseline measured the wrong service.** A dev server was already on
:3000 pointed at a backend on :8000 while the harness spawned its own on :8010.
Preflight passed, the log slice was empty, and the answers came from another
box's cache. Nothing connected the two. `checkWiring` now reads the browser's
own resource timings and aborts when the site is calling a backend this run does
not own.

**A test passed for the wrong reason.** The memory probe planted its fact at
exchange 8 and asked at turn 15, by which point the fact had slid out of the
blind spot and into the summary. Inverting the recall order puts the question on
the one turn where it sits in the gap. It still passes, so the six-message hole
did not manifest in fifteen exchanges.

Also: my language assertions were coin tosses. `mustNotMatch: /\b(the|and)\b/`
reads as a language check and fires on a citation or a proper noun; measured, it
fired on "The" inside the very glue phrase the case was about -- the right
verdict reached by accident.

---

## What T0.3 already found

The re-prompt counters, on a signed-out run:

| gate | turns |
|---|---|
| `locale` | 2 |
| `vocab` | 2 |
| `length` | **0** |

Zero length re-prompts undercuts the plan's premise that the length gate
regenerating answers is the top latency suspect. Caveat: that run is entirely
`stella`, and the prompt conflict the plan quotes is `orion`/16-18, so this is
not yet a verdict. The two `locale` fires are direct evidence for T2.4: with no
language rule in any layered prompt, the model answers in the wrong language and
is re-prompted afterwards -- a whole extra model call, and the source of the
mixed-language output.

---

## Open, and needing a decision before the freeze

- **Conversation-memory questions are answered from the corpus.** One run
  recalled "Marisol's secondary-school uniform"; the next answered "You
  mentioned a laptop or a trip as savings goals" -- invented, and cited, so
  neither the citation check nor the floor discriminates.
- **A signed-out complaint now gets the child escalation copy.** The ticket is
  correct, but a frustrated parent is told "You have not done anything wrong."
  That is QA scenario 5, which the client will test. Suggested: pitch on the
  escalation CATEGORY as well as the band, so complaints read neutrally while
  safeguarding keeps the child copy.
- **`MEMORY_WINDOW_ENABLED`** is a live `false` in `.env.example` under a comment
  saying "OFF by default", against a code default of `true`. If production was
  provisioned from that file, memory is off there and the memory regression
  fails against the deployed URL while passing locally.
- **Tracing does not exist.** No LangSmith, OTel or Sentry configuration
  anywhere; the packages are transitive only. "Enable tracing" means choosing
  and adding one.
- **`owns_thread` still admits any caller to an unowned conversation.** Narrowed
  rather than closed: new thread ids are unguessable now, so only the 56
  pre-existing short-id rows remain resumable by name. A real fix binds the
  conversation to the token's device id and needs a column.

## Deferred, deliberately

The deployed-URL run. It writes real rows, spends real model calls, and the
complaint case raises a real escalation ticket someone monitors. `--against`
is built and its readiness probe is verified against production; the run itself
waits for the freeze, when the team can be warned.
