# Phases 3 and 4 — delivery, reliability, hygiene

2026-08-14 · branch `fix/judging-readiness` · continues `phase-2.md`

Nine commits. **The judging suite is 13 of 13**, from 8 of 12 at the start of
this work. `baseline/judging.json` is empty for that suite now, which is the
strongest form it takes: any failure is a regression rather than a known red.

---

## T3.1 — the reader gets the answer the gates approved

Six outbound gates plus `ground_check`'s decline all ran a graph step AFTER the
agent whose text they were correcting. The agent's message went out during the
agent's step; the corrections landed one step later, in state only. They were
correcting a copy nobody saw.

The fix is small because the architecture allowed it: nothing streams tokens.
Every prose call is `ainvoke`, so LangGraph emits one message per turn and the
reader was already waiting for the whole answer. There was never an incremental
stream to protect, so holding it costs nothing in perceived speed.

It also closed a divergence nobody had noticed: `record.reply` read the
interceptor's accumulated prose -- the uncorrected text -- so Postgres and the
response cache kept one version while the checkpoint kept another, and the model
read back an answer the reader had never seen.

**Two things I broke doing it.** A card turn -- a game, the eligibility wizard --
speaks entirely through a directive and adds no message, so the thread ends on
the reader's question; looking backwards for the most recent assistant message
walked past it and served the PREVIOUS turn's answer again. In the browser: your
last answer reappearing under an unrelated question, and the app never settling.
And the held events still took ordinals with them, so the reader's first frame
arrived numbered 2 -- which nothing noticed, because `OrdinalBuffer.text()`
skips absent ordinals and the test asserted only monotonic-and-unique.

**And a test that was worse than no test.** My first attempt at the card-turn
regression went through HTTP and passed against the bug and the fix alike: the
stream fixture runs without a checkpointer, so nothing carries between requests
and the thread never HAS a previous answer to serve by mistake. Extracting
`final_reply` and testing it directly gave a test that fails against the bug.

**One consequence worth naming.** Once a decline REPLACES the answer rather than
trailing it, the decline's language stops being cosmetic. A French question in
an English session was answered in French by the model and declined in English
by the template -- a blemish before, the whole reply now. `_locale` reads what
the reader wrote, falling back to the session when `detect_locale` cannot tell.

---

## T3.2 — measured before optimising

Both halves of the lexical retriever were rebuilt per turn, on the critical path,
for data that changes only when `ingest` runs.

| | before | after |
|---|---|---|
| corpus read (full table SELECT + filter) | 610-720 ms warm, 4.9 s cold | **0.0 ms** |
| BM25 tokenise + index build | 114-200 ms warm, ~500 ms cold | **3.6 ms** |

Identical results. Keyed on the corpus fingerprint that already existed for the
answer cache, and cleared explicitly by `ingest` -- because re-ingesting the same
CSV leaves the fingerprint unchanged and would otherwise serve rows the
transaction had just deleted.

---

## T3.3, T3.5, T3.6

**Retries.** Nothing in `app/` retried anything. `tenacity` sits in the lockfile
as a transitive dependency and is imported nowhere; the only backoff was one
retry on the Valkey client. A single dropped connection turned a good answer into
"The assistant is temporarily unavailable" -- the likeliest reading of "The
assistant could not be reached" during the 11 Aug demo, which T2.2 could not
account for from the persona code. A permanent failure is not retried: a key that
cannot reach a model 403s, and this project has met that one.

**Email links.** Both were broken, in opposite ways, and `_redeem`'s purpose
matching had no test at all. The confirm-your-email link redeemed against the
sign-in endpoint -- right token, wrong door -- so it always reported "That link
has been used", which was untrue. The passwordless link's token was dropped in
`validateSearch` before anything could look at it. `POST /api/auth/verify`
existed the whole time with no caller.

**The memory hole.** One constant was doing two jobs: deciding WHEN to summarise
(12 messages) and WHERE the summary ends (also 12), while the prompt carries 6
verbatim. Messages 7-12 back were in neither. Only the boundary moved; the
trigger stays at 12, because summarising a four-message thread spends a model
call compressing nothing.

**T3.4 is partial, and labelled so.** The guaranteed half -- a mount effect that
overwrote whatever had been typed -- is fixed. The rest depends on React
hydration timing, which needs measuring in a browser rather than reasoning about,
and a wrong fix there is worse than the workaround the e2e harness already
carries.

**T3.7 untouched**, as the plan requires.

---

## T4.3 — the tests were certifying a prompt nobody reads

Three test files asserted safety properties of `app/prompts.py`, which belonged
to the v1 pipeline. `main.py` carries the tombstone. Nothing has composed
`ASPIRE_SYSTEM_PROMPT`, `GAMES_INSTRUCTIONS`, `memory.build_prompt` or
`rag.context_from` since, so passing said nothing about the live service.

It was not harmless. Retargeted at the real layers, one assertion **failed**: the
shipped prompt had no rule against narrating the search, and the deleted one did.
The symptom was already in the judging transcript --

> "The extracts only explain that a capital gain is profit from selling an
> investment."

-- the reader being told about the retrieval instead of answered. "Answer, do not
narrate" is back in `GLOBAL`, pinned load-bearing.

The dead code itself is left in place. Deleting ~200 lines four days before a
freeze buys tidiness and risks a surprise; the misleading part was the tests.

---

## What Phase 4 did not do

**T4.1, persona renames.** Blocked on the SKN name shortlist. No mechanism built:
a config map for names that may not arrive is speculative work during a freeze,
and the display-name layer is a small change whenever they do.

**T4.3(ii), the eleven bypass call sites.** Not routed through the layered
prompt. The highest-impact one is `_reprompt`, which rewrites an answer with no
persona or band card -- though `safety_out` does state the band in its own
instruction, so it is not blind. Left for after the 21st.
