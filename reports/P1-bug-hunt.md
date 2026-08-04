# P1 — Correctness and bug hunt

Diagnosis only. No production code was modified. Two new test files were added
(they are the pass deliverable); nothing else changed.

Every finding below was confirmed by reading the code, and the parser findings
were additionally confirmed by **executing** the parser and recording its output.

---

## 1. Deliverable: failing regression tests

Written before any fix exists, as required. **All 11 fail today.**

### `frontend/src/lib/aspire/knowledge.regression.test.ts`

```
✖ P1-004: two identical bracketed runs render identically
✖ P1-004: a citation marker keeps its brackets
✔ P1-004: bracketed text mid-sentence is untouched      ← control, proves the defect is positional
✖ P1-005: an ordered list is distinguishable from an unordered one
✖ P1-006: repeated list items are safe to render
✖ P1-007: a stray ** does not bold the remainder of a settled answer
```

Run with `node --test src/lib/aspire/*.test.ts`.

**No test framework was added.** Node 26 executes TypeScript directly and ships
`node:test`, so this costs nothing in the dependency tree — which matters given
the project currently has no frontend test runner at all. Wiring an `npm test`
script is left to P11 so this pass changes no configuration.

### `backend/tests/test_p1_regressions.py`

```
✖ test_open_conversation_records_the_question          (P0-004)
✖ test_title_endpoint_requires_a_session               (P1-001)
✖ test_llm_routes_are_rate_limited[/chat]              (P1-001)
✖ test_llm_routes_are_rate_limited[/chat/stream]       (P1-001)
✖ test_llm_routes_are_rate_limited[/api/title]         (P1-001)
✖ test_voice_cache_writes_do_not_block_the_event_loop  (P1-002)
```

`suggest_title` is stubbed in the auth test: a regression test that spends real
tokens on every CI run would be its own small version of the bug it reports.
Stubbing dropped the file from 10.3s to 2.9s, which is itself evidence the
unauthenticated endpoint really does reach the model.

---

## 2. The parser defects, shown rather than described

Executed against the live `parseAnswer` / `parseInline`:

| Input | Rendered today | Should be |
|---|---|---|
| `Choose [A] or [B]` | `Choose [A] or B` | `Choose [A] or [B]` |
| `See note [1]` | `See note 1` | `See note [1]` |
| `Save 10% ** of income` | `Save 10% ` + **bold tail forever** | no bold |
| `1. Get a form` / `2. Sign it` | `<ul>` bullets, numbers stripped | `<ol>` |
| `- Yes` / `- No` / `- Yes` | `items: ["Yes","No","Yes"]` → duplicate React keys | unique keys |

The bracket defect (P1-004) is the sharpest of these because it is *positional*:
`PARTIAL_LINK` is anchored to `$`, so in a sentence with two bracketed runs the
first keeps its brackets and the last loses them. The control test proves this —
`Fill in [your name] on the form` renders correctly, because the brackets are not
at the end.

That regex exists for a good reason (hiding half-typed markdown links during the
reveal). The bug is that it is applied to settled text as well as revealing text.

**Why P1-005 matters more than it looks.** `How do I apply for ASPIRE?` is one of
the four starter prompts on the landing screen (`knowledge.ts:264-269`). A
numbered application procedure is the single most likely answer shape behind it,
and the numbers are being dropped for an audience of 5-18 year olds.

---

## 3. Backend: blocking work on the event loop

The pack calls this the highest-yield backend class. Result: **one real instance,
and one widely-assumed instance that turned out to be false.**

**Real — P1-002.** `voice/router.py:190 async def speak` does synchronous
filesystem work directly on the loop: `cache.get` reads a whole MP3 and touches
its mtime; `cache.put` writes a temp file, renames it, then runs
`evict_if_needed`, which globs `*.mp3` across the cache directory and `stat`s
every entry — **on every synthesis**. Cost grows with cache occupancy, and under
`--workers 1` it serialises against live chat turns.

**Not real — retrieval.** I expected sync Chroma + sync OpenAI embeddings inside
an async agent to block the loop. Verified against the installed source instead
of asserting it: `langchain_core/retrievers.py:158` and `:323` show
`BaseRetriever` supplying an async `_aget_relevant_documents` that delegates via
`run_in_executor`. Retrieval runs in the default threadpool. **It does not block
the loop.**

The real risk there is different and belongs to P9: that threadpool is the
concurrency ceiling for retrieval in a single-worker process, and its default
size was never chosen deliberately.

---

## 4. The cost surface

`/chat`, `/chat/stream` and `/api/title` all spend model calls. None is rate
limited. `/api/title` additionally has **no auth dependency at all** — it is the
only endpoint in the product that requires no identity whatsoever, accepts up to
28,000 characters, and makes a model call per request.

The service does have good rate limiting — in the voice layer
(`voice/limiter.py`) and on anonymous session creation (`sessions.py:125`). It
was simply never applied to the expensive path. Combined with P0-002 (a turn
cannot be cancelled, so abandoned generations bill in full) and P0-003 (every
prior turn's retrieved documents are replayed into every prompt), the cost
exposure is the strongest argument in this report for not launching as-is.

---

## 5. Contract layer

Diffed `frontend/src/lib/aspire/api.ts` against `backend/app/schemas.py`
field by field. **The contract holds.** `ChatResponseBody` matches `ChatResponse`,
including the nullable `game_started` / `eligibility_started` shapes, and every
optional field has a client-side default (`?? []`, `?? ""`, `?? 0`). The
`snake_case` → `camelCase` mapping is done in one place per transport.

Two mismatches, both about limits rather than shapes:

- `message` is capped at 8,000 server-side and uncapped client-side (P1-008).
- `TitleRequest.answer` has `min_length=1`; `answerToText` can return `""`. The
  resulting 422 is handled correctly by `title.ts` — this is a wasted round trip,
  not a bug.

---

## 6. What I did NOT determine, and why

Stated plainly rather than left as implied coverage.

1. **Mid-stream persona and language switching.** The pack asks for
   persona-switch-mid-stream and language-switch-mid-stream races. There is no
   real stream (P0-001), so the question becomes "switch during an in-flight
   request", which needs the app running to answer honestly. **Outstanding.**
2. **Gamification flow (critical path d).** Not traced end to end. The structure
   is sound-looking — the client loads authoritative state from `/games/*` rather
   than trusting model prose, and `tests/games/test_no_answer_leak.py` exists —
   but I did not verify score persistence or the mid-game reload path.
3. **Transaction and session scope.** I did not read `db/repository.py` or
   `db/engine.py` closely enough to make claims about connection leaks, rollback
   on exception, or transactions held open across a model call. The pack flags
   the last of these as a killer at concurrency; it deserves a proper look in P7.
4. **Concurrency behaviour.** "What breaks at 100 simultaneous conversations" is
   a load-test question (P9), not a code-reading one. The two candidates I would
   watch first are the retrieval threadpool and `InMemorySaver` growth.
5. **`settledBlocks` failure modes.** The pack asks for tests covering
   unterminated code fences, tables split across chunks, and multibyte splits.
   `settled.ts` is dead code (P0-001) *and* `parseAnswer` has no fence, table, or
   setext construct at all — its `assertLineLocal` guard documents exactly that
   precondition. Writing those tests now would be testing a parser against
   syntax it does not implement, for a module nothing imports. **Deliberately
   skipped**; revisit only if P0-001 is resolved by adopting the real stream.

---

## 7. Summary

**10 findings this pass: 1 × S1, 7 × S2, 2 × S3.** Ledger now holds 20 findings
(4 × S1, 12 × S2, 4 × S3), plus 10 items verified sound.

**Worst finding: P1-001** — three endpoints that spend model calls, none rate
limited, one with no authentication at all. For a government-funded product this
is an open budget line.

The most *interesting* finding is P1-004, because it shows the shape of the
real problem in this codebase: a mechanism built correctly for streaming
(`PARTIAL_LINK` hiding half-typed links) is still running over settled text, in
an app that no longer streams. P0-001 and P1-004/007 are the same root cause seen
from two directions — the streaming architecture was removed from the live path
but its accommodations were left behind.

Four things I expected to find and did not: XSS through the markdown renderer
(structurally impossible — no `innerHTML`, allowlisted hrefs), event-loop
blocking in retrieval (verified delegated to a threadpool), leaked internals in
client-facing errors (mapped cleanly), and the send-during-turn race (properly
guarded by a committed ref). Those are recorded in the ledger so P9 and P11 do
not spend time re-deriving them.
