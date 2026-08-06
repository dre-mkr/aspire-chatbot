# P15 — The LangGraph platform

Branch: `feat/aspire-langgraph-platform`, committed as `efbaec6` — 208 files,
+38,749/−3,772. Not merged; the branch is the deliverable for review.

## What this is

The graph is now the product. `POST /v2/chat/stream` is the only way to hold a
conversation with ASPIRE, and every turn goes through:

    hydrate → guard → safety_in → cards → classify → «agent» → safety_out → persist
                                    │                              ▲
                                    └────────── card turn ─────────┘

`/chat` and `/chat/stream` are **gone**, along with `app/streaming.py`, the
single-system-prompt agent in `app/agent.py`, and the `GRAPH_ENABLED` flag that
used to gate the new path. That removal is the substance of the second half of
this work, and it was done rather than deferred for one reason: the old path was
one agent behind one prompt, with no age band, no access matrix, no outbound
gate and no router. Keeping it beside the graph would have left a second door
into the same product with none of those, which is the door that gets left open.

The flag went with it. A switch that can unmount the only chat path is not a
safety control; it is an outage one environment file away.

## The measured record

Every number below was produced on this tree. Nothing here is asserted.

| Metric | Threshold | Measured |
|---|---|---|
| routing accuracy | > 85% | **97.5%** (39/40) |
| widget primitive selection | > 80% | **87.0%** (87/100) |
| widget validation pass rate | > 95% | **100%** |
| widget over-trigger rate | < 15% | **10.8%** (4/37) |
| safety pass rate | — | **100%** |
| band violations | = 0 | **0** |
| formula domain failures | = 0 | **0** |
| ungrounded answers served | = 0 | **0** |
| PII leaks into summary | = 0 | **0** |
| in-KB questions starved of context | = 0 | **0** |
| p50 added latency vs prose-only | < 400 ms | **0.35 ms** |

`make eval` is green on every threshold it gates. `app/graph/access.py` has
**100% branch coverage** over 742 parametrised cases.

Backend: **2,617 pass, 1 xfail, 0 fail** — the whole suite including the slow
one, exit code 0, in 25m40s. The two failures this report previously carried as
"pre-existing and unrelated" are now resolved rather than excused; see P15-006.

Frontend: `tsc --noEmit` clean, `biome check` clean across all 87 files, 39
`node:test` cases pass, production build succeeds.

### Verified in a browser, not only in tests

The whole path was driven through the real client against the real service and
the real Neon database:

* **an ordinary question** — `/v2/session` mints a token, `/v2/chat/stream`
  answers, prose reveals, the "1 source" disclosure and two follow-up chips
  render, and the turn lands in `conversations` + `messages` with its citations
  and chips in `extra`;
* **the response cache** — the same question a second time replayed in 2.5 s
  against 21 s cold, and the replay persisted the turn (which `/chat` did not —
  see P15-011);
* **the eligibility card** — "Who is eligible to join ASPIRE?" opens the real
  five-question flow, with its own first question and its own options, and no
  prose beside it;
* **the admin portal** — email + password sign-in, the forced
  password-rotation gate blocking the queue, and the queue rendering once it
  cleared;
* **a widget interaction** — the agent replies with the child's own numbers
  ("With monthly EC$25, months 12, you get EC$300…") and the mastery row lands
  in Postgres with its next-due date.

**Fourteen real defects were found this way and none of them by a test** —
P15-007 through P15-019, and P15-023, below. Six had been live since the code
was written and would never have surfaced in CI, because each fails in the safe
direction: a 401, an escalation to a human, a ticket, a swallowed write, a
30-second timeout. Nothing crashed and nothing lied.

Four of the six made a whole capability unreachable while every test that
covered it passed — the 9-12 band could not hold a conversation, anonymous and
13-15 readers retrieved nothing ever, the entire mastery track could not write a
row, and (P15-023) no conversation on Windows had any memory at all. In each
case the tests exercised the logic against fakes and the gap was in the wiring
between the logic and its runtime.

### Re-driven after this pass, on the fixed tree

Every claim below was re-observed on `python -m app.serve`, against the real
Neon database, after the changes in this report:

* **a three-turn conversation** — each answer carries its "1 source"
  disclosure and two follow-up chips; the thread wrote **34 checkpoints / 64
  blobs**, and turn 3's query rewriter carried a fact out of turn 2
  (`'Who funds the initial ASPIRE grant?'` → `'…under the ASPIRE Bill, 2024?'`),
  which is only possible if the checkpoint was read back and deserialised;
* **the persona menu** — Stella "Ages 5–12" and Orion "Ages 13–18", rendered,
  matching the access matrix (P15-017);
* **a game card** — "let's play a game" returns "which one would you like to
  play?" with three chips, and the log shows **no model call at all** on that
  turn: the deterministic matcher ran ahead of the classifier (P15-013);
* **the eligibility card** — "QUESTION 1 OF 5", its own first question and its
  five options, with no prose beside it;
* **an escalation** — an ungrounded question for an anonymous reader escalates,
  the `EscalatedDirective` renders as a card with its reference, and the ticket
  row lands in Postgres (`ASP-9A47C0FF`);
* **the checkpoint allowlist** — decoding that live thread reconstructs
  `EscalatedDirective` ×4, `AIMessage` ×4 and `HumanMessage` ×7 as real models,
  with **0 blocked or unregistered-type warnings** (P15-022);
* **the arq worker** — starts as `1 functions: cron:retention_job` with an empty
  on-demand list, and drained the stale summary backlog described in P15-021.

## Findings

### P15-001 — a similarity threshold cannot decide groundedness · **decided**

The obvious design for `ground_check` is a cosine floor. Measured on the real
706-row corpus with a local embedding model:

```
in-KB      n=30   0.614 .. 0.873   (median 0.735)
out-of-KB  n=20   0.443 .. 0.757   (median 0.652)
```

The populations **overlap**. The best possible threshold still misclassifies 11
of 50. The worst cases are the most dangerous: *"Can I get a loan against my
child's ASPIRE account?"* scores 0.757 — higher than most real questions —
because it is about savings accounts in every respect except that no such
product exists.

**Decision.** The cosine floor sits at 0.55, below the lowest real question, and
does one job: reject the case where nothing retrieved is the same subject. What
decides groundedness is **attribution** — the answer must cite a retrieved row,
the cited row must be one actually retrieved, and every figure must appear in a
chunk. On that gate, ungrounded answers served = 0.

`grounding_cosine_overlap` is reported on every eval run (11 today) so the
finding stays visible.

### P15-002 — dense chunks carried a synthetic id · **fixed**

`_search` read `metadata["kb_id"]`; ingest writes the row id under
`metadata["id"]`. Every dense chunk got `row-0`, `row-1`, … Two silent
consequences: RRF could not match a dense hit to the same row from BM25, and the
model's **correct** citation was rejected as invented. Fixed in
`agents/qa/graph.py`.

### P15-003 — internal model calls streamed to the reader · **fixed**

`stream_mode="messages"` streams tokens from *every* model call in the graph.
The first end-to-end run put the classifier's
`{"agent":"qa_agent","confidence":0.99}` on screen in front of the answer.
`StreamInterceptor.INTERNAL_NODES` now drops tokens from `classify`,
`rewrite_query`, `safety_out`, `plan_widget`, `doc_check`, `persist` and
`summarise`.

### P15-004 — the RESET sentinel was not serialisable · **fixed**

A singleton class raised `Type is not msgpack serializable` the first time a
turn was checkpointed — i.e. only on the deployment with a database. `RESET` is
now a module-level string.

### P15-005 — `a11y_text` was held to the caption length cap · **fixed**

Gate 6 applied the caption cap (12 words at 5-8) to the screen-reader text.
Every shipped few-shot failed, because twelve words cannot describe a widget.
`BAND_A11Y_WORDS` is a separate, much larger cap.

### P15-006 — the Chroma comparison measured the corpus, not the backends · **fixed**

`test_retriever_equivalence.py` ×2 compared a stale local Chroma baseline
against the re-ingested Neon corpus. Left open here as "pre-existing and
unrelated", which was true and was not a resolution: two red tests that nobody
intends to fix are indistinguishable from two red tests nobody has looked at.

Counted rather than assumed:

```
chroma  332 rows        neon  706 rows
only in neon    374     (all FIN-*, added after the snapshot)
only in chroma    0     -- the move dropped nothing
```

So the failures were **the corpus difference, reported as a retrieval
regression**. pgvector returned FIN-304 for "How is the ASPIRE financial
education delivered?" at cosine distance 0.209 — a better hit than anything
Chroma holds — and the test read that as a divergence 5.1e-02 outside
`NOISE_BAND`. A new row winning is the corpus working.

`data/chroma` is a gitignored snapshot taken at the migration, and nothing in
this codebase can rebuild it: `app/rag.py` dropped Chroma deliberately. So the
comparison is now **restricted to the 332 ids the baseline actually holds**,
which restores the controlled experiment the file always described — same
documents, same query vector, two backends. On that footing the original claim
still stands, measured on all 30 probe questions:

```
rank-1 divergences                  0
top-5 differences beyond NOISE_BAND 0
```

The equal-count assertion is replaced by a containment one — every baseline id
is still in Postgres — because a count stopped meaning what it said the moment
the knowledge base grew, while "the move lost a row" is the property the
migration actually promises and survives the corpus growing.

The restricted ranking is computed in numpy, since `PgVectorRetriever` cannot
filter by id. That is sound only because `test_pgvector_ranking_is_exact` proves
pgvector reproduces this exact numpy ranking element for element over the whole
corpus; the transitivity is asserted, not assumed. **12 passed, 0 failed.**

*(The third item previously listed here,
`test_streaming.py::test_a_continuing_turn_does_not_pay_for_chips`, is resolved
by deletion: it tested `/chat/stream`, which no longer exists.)*

---

The next thirteen were found by running the product, after every test passed.

### P15-007 — every anonymous session was rejected on its first message · **fixed**

`mint_session_token` wrote `"sub": user_id` unconditionally, so a session with
no account — the **default** path, and the one a child on a school tablet takes
— was signed with `"sub": null`. RFC 7519 requires `sub` to be a StringOrURI and
PyJWT enforces it on decode, so:

```
mint   → a well-formed JWT
decode → InvalidSubjectError → None → 401 "Please sign in again"
```

Both halves looked correct in isolation, which is why nothing caught it: the
mint returned a valid token and the decode failed closed exactly as designed.
Only a round trip shows it, and there was no round-trip test.

`sub` is now **omitted** when there is no user. `tests/graph/test_identity.py`
is new and its first test is that round trip.

### P15-008 — the audience filter matched nothing, ever · **fixed**

`_permitted` tested for `"public" in tags` and `"youth" in tags`. The knowledge
base uses neither word. Counted on the live table:

```
student 246   parent 188   general 166   child 57   teacher 49
```

So `qa_agent_public` and `qa_agent_limited` — the agents serving anonymous
visitors and every 13-15 reader — retrieved **nothing on every turn since they
were written**. `_corpus("public")` returned 0 rows against 706 for `all`.

It failed in the safe direction, which is why no wrong answer was ever produced
and why it was invisible: retrieval returned empty, `ground_check` refused to
answer without context, and the turn escalated to a human. An anonymous visitor
simply got a ticket instead of an answer, always.

`AUDIENCE_TAGS` now maps the corpus's real vocabulary. `general`, `student` and
`child` reach both filtered agents; `parent` and `teacher` do not, because
guardian consent and classroom guidance are not answers for a child. Both slices
now hold 469 rows.

### P15-009 — the response cache key had no age band · **fixed**

`safety_out` caps a reply at 35 words for 5-8, 70 for 9-12 and 180 for 16-18.
The cache keyed on language, persona and account status — and **one persona
spans three bands**: `orion` is the mascot for 9-12, 13-15 and 16-18 alike.

A 180-word answer written for a sixteen-year-old was therefore servable, whole,
to a nine-year-old — and a cache hit never reaches the gate that would have cut
it. Introduced by reusing `/chat`'s key on a path that has bands.

`age_band` is now part of the key and the key version is `v2`, which retires
every existing entry. `tests/test_cache_keys.py::TestAgeBand` pins it.

**Layer 2 now has the band too.** This report previously deferred it, on the
reasoning that fixing a path with no callers is churn that cannot be tested.
That reasoning was wrong: `tests/test_semantic_cache.py` exercises the layer
directly with the flag forced on, and it is where the deferral was written down.
So `semantic_shelf_key`, `semantic_lookup` and `semantic_register` all take
`age_band`, the shelf key is `semindex:v2:`, and
`test_the_shelf_never_crosses_an_age_band` registers an answer at 16-18 and
fails the lookup at 9-12 with a near-identical vector.

The band had to go into **both** the shelf key and the `cache_key` each entry
points at. Only the first would have aimed every entry at a key layer 1 never
wrote — a permanent, silent miss that would have made the layer dead on arrival
the day somebody switched it on.

Still off and still unwired, and neither is a leftover: `semantic_cache_enabled`
defaults to False on P14-B's measurement (an adversarial near-pair, "aged 5 to
18" ~ "aged 5 to 12", sits at 0.9645 cosine while every genuine paraphrase falls
below the 0.95 threshold), and wiring it into the graph would cost a query
embedding (~400 ms) *before* routing, on every turn including the card turns and
refusals that never retrieve. Both facts are now written where the code is,
rather than as a note asking the next person to finish the job.

### P15-010 — the client gave up before the graph finished · **fixed**

`lib/stream/client.ts` inherited `TIMEOUT_MS = 45000` from the v1 streaming
transport. A graph turn is strictly more work than the single agent call that
number was chosen for. Measured live on a cold reranker, an ordinary Q&A turn
took **21–46 s** — so the reader saw *"That took too long"* over a turn the
server went on to complete and bill. Observed in the browser on the second
question asked.

Now 90 s, inside the server's own 120 s backstop so the client gives up first
and the reader gets a message written for them rather than a closed socket.

### P15-011 — a cached first turn stranded its question · **fixed in passing**

`/chat`'s cache hit returned without recording anything. When the hit was the
first turn of a thread, the client had already committed the chat to the URL and
the rail, and the conversation had no reply behind it. The v2 replay path opens
the conversation and persists the turn like any other; verified in the database.

### P15-012 — citation markers reached the reader · **fixed**

`[ASP-001]` is grounding machinery: `ground_check` parses it to prove the model
can point at the row it used, and the ids then travel as a `citations` directive
which the transcript renders as a "1 source" disclosure. That left the marker
itself with nothing to do except sit in the middle of a sentence a six-year-old
is reading.

Stripped in `StreamInterceptor`, not at the model — telling the model not to
write them would remove the grounding check's only input. The fiddly part is the
space in front: a chunk boundary falls inside a nine-character marker
constantly, and releasing the space early leaves a double space and a stranded
" .". Tested at chunk sizes 1, 2, 3, 4, 5, 7, 9, 13, 40 and 500.

### P15-013 — the card matcher was placed where routing skips it · **fixed**

`intent_gate` was a node of the **Q&A subgraph**, which looked reasonable and
did not work. The classifier is free to route a turn to `learn_agent` or
`escalate_agent`, and a matcher living downstream of it never runs on the turns
it exists for. Measured against the live service:

```
"let's play a game"          → escalate_agent   (a ticket, for asking to play)
"can we play true or false"  → learning_sample  (a lesson on saving)
```

Recognising a card turn is a **routing** decision, so it now happens where
routing happens: `hydrate → guard → safety_in → cards → classify`. A card turn
goes straight to `safety_out`, which has nothing to gate. The same three
questions now open the eligibility card, open a `true_false` game directive, and
ask which game — all with no model call.

Moved with it: `agents/qa/{cards,intents}.py` → `graph/nodes/{cards,intents}.py`.

### P15-014 — the response cache could answer a card question with prose · **fixed**

`turn.cacheable` refuses to *write* a card turn. The lookup still *read* one:
layer 1 is consulted before the graph, so an entry stored under the same key
before the matcher existed — or before it recognised a phrasing — is prose
sitting where a card turn now hashes to. Observed live: "can we play true or
false" replayed a cached lesson.

The lookup is now skipped for anything `_wants_card` claims, using the same two
matchers the node uses so the cache and the graph cannot disagree.

### P15-015 — the audience filter withheld correct answers from children · **fixed**

The first fix for P15-008 mapped `parent` and `teacher` away from the two child
slices, reasoning that guardian consent and classroom guidance are adult
material. That was wrong, and one live turn showed why: a nine-year-old asking
*"what is the minimum age?"* was escalated to a human, because all three rows
that answer it — ASP-029, ASP-030, ASP-241 — are tagged `parent`.

`parent` in this corpus means "written with a parent as the reader", not
"withheld from a child". *"The minimum age to join ASPIRE is 5"* is a fact any
child may know.

Both slices now hold every tag the corpus uses. What the filter does is
**exclude what is not listed** — a `staff` or `internal` tier added tomorrow is
barred from children without the file changing. Stated plainly in the code:
the audience filter currently has nothing to filter, and making it appear to do
work by withholding correct answers from children is worse than admitting that.

### P15-016 — a follow-up chip restated the question · **fixed**

Chips are corpus questions near the one asked, so the nearest is often the same
question in other words: *"What is the minimum age?"* was offered *"What is the
minimum age requirement for ASPIRE enrolment?"* — a different row, the same
question, and it reads as not having listened.

Exact-match dedupe cannot catch it. `_restates` uses **containment** over
content words rather than symmetric similarity, because the failure is a longer
row restating a short question and Jaccard scores that pair low precisely when
it matters.

The guard needed its own guard. *"What is ASPIRE?"* has one content word, so
containment scores 1.0 against everything mentioning ASPIRE — unguarded, the
product's most-asked question suppressed every chip under its own answer. Below
two content words, only an exact match counts.

### P15-017 — the 9-12 band was locked out of the product · **fixed**

`DEFAULT_PERSONA` in `graph/account.py` mapped 9-12 to `orion`. The access
matrix grants Orion only at 13-15 and 16-18 — `allowed_agents("orion", "9-12",
…)` returns `[]`, which every caller must treat as a hard 403. So every
nine-to-twelve-year-old was issued a token the matrix denies outright, `guard`
halted the turn, and the band could not use the product at all.

Both halves were individually correct: the matrix said what it meant, and the
token was minted exactly as configured. Nothing connected them until a turn was
run for that band.

Resolved towards the matrix, because the matrix is the security control.
`tests/graph/test_account.py` asserts that **every** default persona resolves to
a non-empty agent list, across every band and account status, so this class of
mismatch cannot return silently.

**The copy is now settled too**, which this report left as an open question.
`personas.ts` advertised Orion as "Ages 10–18" and Stella as "Ages 5–9"; it now
reads **"Ages 5–12"** and **"Ages 13–18"**, matching what the matrix grants.

Settled that way round, and not by giving Orion a 9-12 row, because widening
Orion enlarges what a child-band token reaches — a security decision, not a copy
fix. The menu was the half that was wrong: `DEFAULT_PERSONA` had been built from
this blurb rather than from the matrix, which is how the lockout happened in the
first place. Left as it was, an eleven-year-old choosing Orion is refused
server-side by `_narrowing` and silently left on Stella — no longer a lockout,
but still a menu offering something the product will not deliver.

Pinned by `test_the_persona_menu_never_advertises_an_age_the_matrix_denies`,
which parses the real `personas.ts` — a copy of the copy would agree with itself
while the product disagreed — walks each advertised age through `band_for`, and
asserts the matrix grants that persona there. One direction only: everything
advertised must be granted. The converse is deliberately not asserted, since
Stella is granted the `adult` band and no menu should say so.

Checked against the old copy before trusting it: it fails at ages 10, 11 and 12
— exactly the band that was locked out.

### P15-018 — a widget interaction escalated to a human · **fixed**

Three faults stacked, and the D6 loop worked only after all three:

1. **The flag was wiped before anything read it.** The transport put the
   interaction on `safety_flags` in the graph's initial state; `hydrate` clears
   `safety_flags` every turn to drop the previous turn's outputs. It is an
   INPUT, so `hydrate` now reads it off the request body — below the reset,
   where it survives.
2. **Nothing routed on it.** An interaction has no message, so the classifier
   was handed an empty string and escalated. It now resolves deterministically
   to the agent that produced the widget (`active_agent` from the checkpoint),
   falling back through `learn_agent` → `learning_sample` → `learning_preview`
   and never past the access matrix. No model call: there is no decision here.
3. **The learner id was not a UUID.** `user_id or session_id or "anonymous"`
   handed a session id to a UUID column; asyncpg raised, the exception escaped
   the node, and a child who had moved a slider was told the assistant was
   unavailable. Anonymous now means `None`, `MasteryStore.record` accepts it and
   writes nothing, and the reply is unaffected.

The mastery write is also non-fatal now, for the same reason `persist_turn` is:
the reply about the child's own numbers is the point of the turn, and losing a
scheduling hint must not take it away.

### P15-019 — the whole mastery track was unreachable · **fixed**

Chasing P15-018 to the bottom turned up two foreign keys with nothing behind
them:

```
mastery.learner_id → learners   (empty; nothing ever inserted)
mastery.concept_id → concepts   (empty; the YAML was never loaded)
```

So **every** mastery write from a signed-in child raised a foreign-key
violation. The C4 track — mastery, scheduling, spaced repetition — could not
record anything in production, and the test suite could not see it because the
learning tests use the in-memory store, which has no foreign keys to violate.

Two fixes. `PostgresMasteryStore.put` upserts the learner row first, using the
account's own UUID as `learners.id` — the schema allows a separate id, but every
caller in the graph passes `state["user_id"]`, and two different ids would mean
a lookup table nobody consults. And `app/curriculum/seed.py` is new: it writes
the authored modules and concepts into Postgres, idempotently, at startup.

Verified by a real interaction:

```
mastery: learner=11111111… concept=save score=1 touches=1 due=2026-08-08
```

The lesson TEXT stays in the YAML deliberately. The tables carry identity and
ordering so a mastery row can point at a concept; copying the teaching copy into
a database would create a second version of the same paragraph and no answer to
which one a child read.

---

The next three were found while closing this report's own open items. Two are
regressions that this branch introduced and shipped green: each is a constant
that had to change in two places, changed in one, and failed by doing nothing.

### P15-020 — the cache flush swept a key version that no longer exists · **fixed**

P15-009 bumped the answer key from `answer:v1:` to `answer:v2:`. `flush_answers`
still scanned `answer:v1:`, so a knowledge-base reload matched nothing and
deleted nothing — while reporting success, because deleting zero keys looks
exactly like a cache that was already empty. It had been verified working at
**71 keys → 0** before the bump (`docs/latency-baseline.md`).

The corpus fingerprint inside every key means no stale answer was ever *served* —
that guarantee never depended on the flush. What was lost is the reclaim: every
entry from before a reload sat holding memory until its TTL expired.

`scripts/flush_probe_answers.py` carried the same stale literal, and there it is
worse than a missed reclaim. It exists to set up a warm-MISS latency probe:
answers gone, embedding cache warm. Deleting nothing means the probe measures
warm **hits** and reports them under the other name — a measurement error in the
tooling this project uses to make its claims.

Both now derive from one `_FLUSH_PREFIXES`, which lists retired versions
deliberately, and `TestFlushCoverage` derives the live prefix *from the key
builders* and asserts it is swept. Bump a version without touching the sweep and
it fails. Verified live: 3 keys written across all three kinds, `flush_answers()`
returned 3, **0 remaining**.

### P15-021 — the summary job had no caller, and had written nothing · **fixed**

Listed here as a known gap: "`conversations.summary`, written by the arq worker,
is now read by nothing." Half right. It was not being written either.

```
conversations                2,774
with a summary                   0
summarized_through_seq > 0       0
```

Two separate reasons, and the second only turned up when a worker was actually
started during verification:

* `enqueue_summary` lost its last caller when `POST /chat` was deleted, so
  nothing has queued this job since.
* **Before that, the jobs were queued and never run.** A backlog of **1,555**
  `summary:*` jobs was still sitting in Valkey. Starting a worker drained the
  lot as `expired` — they had been queued while `/chat` existed, no worker was
  ever run against them, and they aged past their deadline in the queue.

So the column was empty for the whole life of the feature, first because nothing
consumed the queue and then because nothing filled it.

`summarise_conversation_job`, `enqueue_summary`, `save_summary` and
`turns_awaiting_summary` are deleted. The rolling summary lives in the checkpoint
and `turn.summarise_thread` writes it there after the stream closes.

Removed rather than left wired to nothing, because a registered job that nobody
enqueues is indistinguishable from a broken one: the worker starts, reports
itself healthy, and processes nothing forever. The arq worker itself **stays** —
it still runs the nightly retention sweep, which is the one thing on it that
works. `WorkerSettings.functions` is now `[]` and a test says so on purpose.

The `summary` and `summarized_through_seq` columns are left in place: they hold
no data, and every migration on this branch is additive.

### P15-022 — a third type was unregistered, and only counting found it · **fixed**

The known gap named two types langgraph would stop deserialising, `KBChunk` and
`Citation`. Counted on the live checkpoint tables (2,568 blobs, 3,152 writes),
there were three:

```
KBChunk x560   EscalatedDirective x108   Citation x24
```

Worth stating plainly because of how this fails. A blocked type does not raise —
the ext hook returns the raw payload, so a `KBChunk` comes back as a plain dict
and the first symptom is `merge_citations` raising `AttributeError` on
`citation.kb_id`, one layer away from anything that names a checkpoint.

So the allowlist is **derived** from the real annotations rather than
transcribed: everything reachable from `KBChunk`, `Citation`, the `UIDirective`
union and `Application`. That is 36 types, including all nine widget schemas and
their nested `Control` / `Panel` / `Bucket` models — none of which appear in the
tables today, and every one of which would have hit the same wall the first time
a widget was checkpointed. A hand-written list gets the outer type right and the
third level down wrong.

It is still an allowlist, not `app.*`: `Settings` is a pydantic model in this
codebase and is deliberately not on it. Verified by decoding every stored blob
with exactly this list — **6,568 of 6,568 decoded, 0 blocked, 0 warnings**, with
all 692 model instances reconstructed as models rather than dicts.

### P15-023 — the graph had no persistence on Windows, and said so as a timeout · **fixed**

Found by running the app. Every graph turn logged:

```
ERROR app.graph.checkpointer: The checkpointer could not open a connection pool,
  so this process will run WITHOUT conversation persistence.
psycopg_pool.PoolTimeout: pool initialization incomplete after 30.0 sec
```

The database was fine. Measured on the same DSN, same process:

```
Proactor loop   FAILED after 20.0s   PoolTimeout
Selector loop   OK in 0.8s           select 1 -> {'ok': 1}
```

psycopg's async mode cannot run on Windows' `ProactorEventLoop`. That was known
and `install_windows_event_loop_policy()` existed for it, called at import in
`main.py` with a comment explaining that the lifespan would be too late. The
comment reasoned about the wrong mechanism. uvicorn 0.52 picks its loop with an
explicit factory:

```python
asyncio_run(self.serve(), loop_factory=self.config.get_loop_factory())
# win32 and not use_subprocess -> asyncio.ProactorEventLoop
```

An explicit `loop_factory` **bypasses the event-loop policy entirely**, so the
call was inert no matter how early it ran. `use_subprocess` is only true under
`--reload` or `--workers > 1`, so the ordinary single-worker command was exactly
the one that broke.

The consequence was not a crash. `get_checkpointer` returns None by design when
there is no database, and callers handle it — so the graph ran statelessly:
every turn started from a fresh state, nothing resumed, and no conversation had
any memory of the previous message. The answers still looked right. It failed in
the safe direction and cost 30 s per process start to do it.

It also meant **P15-022's allowlist was never reached in the running app**,
because a checkpoint that is never written is never deserialised.

Two fixes. `app/serve.py` is a new entry point that supplies the loop factory
itself, which is the only place that gets to choose before the loop exists;
`python -m app.serve` replaces `python -m uvicorn app.main:app` for development,
and Linux takes the plain path exactly as before. And `get_checkpointer` now
recognises a Proactor loop up front and says so — 0.47 s and a message naming
the cause and the command, instead of 30 s blaming the database.

Verified end to end afterwards, on one three-turn conversation:

```
Checkpointer tables are present in Postgres.
rewrote 'Who funds the initial ASPIRE grant?'
     -> 'Who funds the initial ASPIRE grant under the ASPIRE Bill, 2024?'
checkpoints 34   blobs 64   unregistered-type warnings 0
```

The rewrite is the proof that matters: it carries a fact from an earlier turn,
which is only possible if the checkpoint was written, read back, and
deserialised into real models.

## What changed in the product

### Gone

| Removed | Why, and where it went |
|---|---|
| `POST /chat`, `POST /chat/stream` | Replaced by `/v2/chat/stream`. ~1,436 lines out of `main.py`. |
| `app/streaming.py` (`TurnBuffer`, `agui_stream`) | `TurnBuffer` existed to discard prose the model wrote alongside a card. Cards are now decided **before** the model runs, so there is no prose to discard. |
| `agent.build_agent` / `get_agent` | One system prompt for readers aged five to adult was the thing an age band could not be built on. Replaced by per-agent prompts inside the subgraphs. |
| `agent.suggest_follow_ups` | A second model call per turn that invented two chips from the question and answer alone. It had no idea what the corpus contained, so a suggestion was as likely to be a question ASPIRE cannot answer as one it can. |
| `askAspire` (frontend) | The non-streaming fallback. There is nothing to fall back to, and a second path answering the same question differently is how a streaming transport becomes a second product. |
| `GRAPH_ENABLED` | See above. |
| `@tanstack/ai-client` | Gone with AG-UI, and removed from `package.json` rather than left installed. It was used for one thing — an SSE connection adapter — and `lib/stream/client.ts` reads the body itself, with a frame splitter tested directly under `node --test`. |

### Changed for the reader

* **Follow-up chips now come from retrieval.** Two questions the knowledge base
  can actually answer, taken from the fused result the turn already produced —
  for no extra model call, and every one of them has a row behind it.
* **A card turn produces no prose at all.** "Can I join?" and "let's play a
  game" are matched deterministically before anything is embedded
  (`graph/nodes/intents.py`), so the eligibility and game cards arrive with
  nothing beside them. A regex cannot be talked out of opening the card, which a
  tool description can.
* **Answers are band-gated.** Length, vocabulary, PII, links, chips and locale,
  in that order, on every path including the refusals.
* **Conversations are owner-checked.** `/chat` read history by thread id alone.
  A thread with a different owner is now refused.
* **Directives render.** Widgets, upload cards, review cards, progress and
  escalation now reach the screen — `Transcript` renders `DirectiveView` under
  each settled answer. Before this they existed end to end on the server and
  were rendered by nothing.

### Kept working, unchanged for the user

History and the rail, titles, the response cache, rate limiting, personas,
"explain it simply", the language setting, the voice layer, the games, the
eligibility card, and the whole reveal/typewriter behaviour. `AskResult` is
still the contract `use-conversation.ts` is written against, which is why the
wire could be replaced underneath it.

## Existing code touched

| File | Change |
|---|---|
| `app/main.py` | −1,436 lines. Now health, readiness, titles and the routers. |
| `app/agent.py` | −148 lines. The chat model, titles, summaries. |
| `app/cache.py` | `age_band` in the key; version `v1` → `v2`. Layer 2 gained the band the same way (`semindex:v2:`), and `_FLUSH_PREFIXES` replaced the two stale literals that swept `v1` — see P15-020. |
| `app/jobs.py` | The summary job, `enqueue_summary` and `SUMMARISE_TASK` removed (P15-021). Cron-only now: the nightly retention sweep is all that is left, and it is what the worker was actually doing. |
| `app/db/repository.py` | `save_summary` and `turns_awaiting_summary` removed with it. `load_context` stays and is called by nothing. |
| `app/graph/checkpointer.py` | An explicit msgpack allowlist on the saver's serde, derived from the state's own annotations (P15-022). Plus a Proactor-loop guard that fails in 0.47 s naming the cause, instead of a 30 s pool timeout blaming the database (P15-023). |
| `app/serve.py` | **New.** The entry point that supplies uvicorn's loop factory, which is the only way to get a loop psycopg can connect on. `python -m app.serve` replaces `python -m uvicorn app.main:app` for development; Linux is unaffected either way. |
| `app/main.py` | The import-time event-loop-policy comment corrected: it claimed to fix the Windows checkpointer and could not, because uvicorn's explicit `loop_factory` bypasses the policy. The call is kept for the callers that *do* go through it. |
| `app/graph/account.py` | The `DEFAULT_PERSONA` note now records the copy as settled rather than as an open question. |
| `frontend/src/lib/aspire/personas.ts` | Orion "Ages 10–18" → **"Ages 13–18"**, Stella "Ages 5–9" → **"Ages 5–12"**, matching the access matrix (P15-017). |
| `frontend/vite.config.ts` | Formatting only. It was the one CRLF file in the tree and the only thing `biome check` failed on — pre-existing, and fixed because this report claims biome is clean. Indentation and one line wrap; no semantic change. |
| `scripts/flush_probe_answers.py` | Derives its prefixes from `_FLUSH_PREFIXES`. It had the same stale `answer:v1:`, where deleting nothing turns a warm-MISS probe into a warm-HIT one. |
| `tests/test_retriever_equivalence.py` | The Chroma comparison is restricted to the ids the baseline holds, and the count assertion became a containment one (P15-006). |
| `app/limits.py` | `graph_rate_limit`, metered on the session token, same bucket as before so a caller cannot double their budget with two token types. |
| `app/config.py` | +70 lines of settings; `graph_enabled` removed. |
| `app/rag.py` | +42/−0 (`asearch_with_scores`). |
| `app/schemas.py` → `app/schemas/http.py` | Became a package; `__init__.py` re-exports every name. |
| `evals/run.py` | `score_answers` repointed from `get_agent` to the QA subgraph. Its retrieval figures are now measured against the fused + reranked retriever, so they are not comparable to the P8 baselines. |
| `frontend/src/lib/aspire/stream.ts` | Rewritten onto `/v2/chat/stream`, same `AskResult`. |
| `frontend/src/lib/aspire/api.ts` | `askAspire` removed; `directives` added to `AskResult`. |
| `frontend/src/components/chat/Transcript.tsx` | Renders `DirectiveView` under each settled answer. |
| `frontend/src/components/chat/AspireChat.tsx` | Builds the `DirectiveContext`. |
| `backend/pyproject.toml` | New dependencies, plus two pins that were being relied on transitively: `langgraph-checkpoint==4.1.1` (its `>=3.0.1` floor resolves to a version `langgraph 1.2.10` cannot import — the first failure of this whole piece of work, and it presents as the graph package being broken) and `bcrypt==5.0.0` (the hash behind the admin credential). |
| `backend/scripts/{latency,session}_probe.py` | Repointed at `/v2`, including the session mint and the new event format. Both would have 404'd. |
| `frontend/package.json` | `@tanstack/ai-client` removed. |
| `.env`, `.env.example` | `GRAPH_ENABLED` removed. **`PII_ENCRYPTION_KEY` in `.env` is a development key and must be rotated before this deployment holds a real application.** |

## New modules worth knowing about

* **`app/turn.py`** (521 lines) — everything a turn does besides producing the
  answer: the owner lookup, the conversation write, persistence, the cache, and
  the rolling summary. Deliberately outside the graph, so the graph can be
  invoked with no database at all — which is how the eval harness and every
  subgraph test run it.
* **`app/graph/account.py`** — derives `persona`, `age_band` and
  `account_status` from the `users` row. The client may request a *narrower*
  persona and never a wider one; the check runs the real access matrix both ways
  rather than approximating it.
* **`app/graph/nodes/intents.py`** / **`cards.py`** — the deterministic card
  matcher, in three languages, with a lookup list that wins ties so *"what is
  the minimum age?"* stays an ordinary cited answer. It sits between
  `safety_in` and `classify`; see P15-013 for why that position is not
  cosmetic.

## Migrations applied to the dev Neon database

`alembic upgrade head` was run. Six additive revisions — no existing table is
altered or dropped: `0010_tickets`, `0011_curriculum`, `0012_mastery`,
`0013_concept_widgets`, `0014_applications`, `0015_staff`.

The checkpointer created its own four tables via `AsyncPostgresSaver.setup()`.

## Closed since this report was first written

Every code-level gap below has been resolved, with the measurement beside it.
What remains after them is configuration and one number, and is listed separately.

| Was | Now |
|---|---|
| P15-006 open: two slow-suite failures | **fixed** — the comparison measured the corpus, not the backends. 12 passed, 0 failed. |
| Layer 2 lacks the age band | **fixed** — `semindex:v2:`, band in the shelf key *and* the pointer, cross-band lookup test. |
| `conversations.summary` written by nothing | **fixed** — dead job and its two repository helpers deleted; 0 of 2,774 rows had ever been written. |
| `KBChunk`/`Citation` will stop deserialising | **fixed** — 36-type derived allowlist; 6,568/6,568 blobs decode, 0 warnings. A third type, `EscalatedDirective`, was found by counting. |
| Orion's advertised age range contradicts the matrix | **fixed** — "Ages 5–12" / "Ages 13–18", pinned by a test that reads the real `personas.ts`. |
| — | **P15-020** found and fixed: `flush_answers` swept a retired key prefix and reclaimed nothing. |
| — | **P15-023** found by running the app and fixed: the graph had **no persistence at all on Windows**, reported as a 30 s database timeout. Now 34 checkpoints on a three-turn thread. |

## Known gaps, stated plainly

Four of these are configuration on this machine rather than defects in the tree;
they are kept because a deployment has to decide each one.

* **A turn costs 21–46 s on this deployment.** The cross-encoder's first load
  dominates the first turn; after that the answer model does. The cache covers
  repeats. Still the one measurement worth taking before launch, and it is a
  measurement rather than a fix — nothing in this pass changed the shape of it.
* **`CLASSIFIER_MODEL` falls back to `CHAT_MODEL`** here, with a startup
  warning, because there is no Anthropic key. Routing works and costs
  answer-model prices; setting a small model of your own provider fixes that.
* **`DOC_CHECK_MODEL` is unset**, so uploaded documents go to the human queue
  with no automated opinion — exactly the behaviour before the node existed.
* **The seeded staff password was rotated during verification.**
  `reviewer@aspire.kn` no longer holds the password quoted in earlier notes.
* **`PII_ENCRYPTION_KEY` in `.env` is a development key** and must be rotated
  before this deployment holds a real application. Repeated here because it is
  the only item on this list that is a hazard rather than a setting.
* **The semantic cache (layer 2) is off and has no caller.** No longer a gap in
  the sense the earlier draft meant — the age-band hole is closed, and both
  facts are now decisions written at the code with their evidence: the flag is
  False on P14-B's overlap measurement, and wiring it would buy a query
  embedding (~400 ms) before routing on every turn. Left here so nobody
  rediscovers it as an oversight.
* **`load_context` has no caller at all.** `build_prompt` still backs
  `scripts/measure_prompt_tokens.py`; `load_context` backs nothing now that the
  summary job is gone. Left in place rather than deleted in the same pass that
  removed the job, but it is dead and the note above it says so.
