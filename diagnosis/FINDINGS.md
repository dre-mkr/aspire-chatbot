# ASPIRE — diagnostic findings

## Provenance warning — read this first

**This diagnosis was run against a dirty working tree that I modified earlier in
the same session.** 17 files are modified and 6 are new, relative to `c0f9d62`.
The changes touch the learning agent, the access matrix, the response-cache
rule, the stream transport, the knowledge base and the card gate.

That matters because two of the four reported symptoms describe behaviour that
was changed during this session. Every finding below is therefore labelled:

| Label | Meaning |
| --- | --- |
| `HEAD` | Present in the committed tree the maintainer is most likely running |
| `WORKING-TREE` | Introduced by this session's uncommitted edits |
| `FIXED-THIS-SESSION` | Present at `HEAD`, already addressed in the working tree |

A clean re-run against `c0f9d62` would be worth doing before acting on this.

---

## CRITICAL

### F1 — Registration PII is written into the LangGraph checkpoint `HEAD`

**Evidence.** `_persist_state` copies the entire slot dictionary into graph
state, which the checkpointer serialises to Postgres:

- `backend/app/agents/register/graph.py:103-116` — returns `{"values": draft.values, ...}`
- `backend/app/agents/register/store.py:114` — `values: dict[str, Any]`, "keyed by slot path"
- `backend/app/graph/state.py:281` — `registration: RegistrationState | None`
- `backend/app/graph/state.py:219` — `RegistrationState = Any` (untyped, so nothing constrains what lands there)
- `backend/app/graph/checkpointer.py:1-4` — `AsyncPostgresSaver`, `thread_id = session_id`

The slots include national ID and dates of birth:

- `backend/app/agents/register/schema.py:332` — `Slot(path="guardian.national_id")`
- `backend/app/agents/register/schema.py:348` — `Slot(path="guardian.date_of_birth")`
- `backend/app/agents/register/schema.py:104-105` — `national_id: str`, `date_of_birth: date`

**Observed, not inferred.** A read-only probe of the live checkpoint store
(`checkpoint_blobs`, 3156 checkpoint rows, `type = msgpack`):

```
channel 'registration' blobs contain the map key  guardian.full_name
channels carrying application_id                  ['registration']
```

A full name is already PII. The remaining slots reach the same dictionary by
construction — `_persist_state` copies `draft.values` wholesale, with no
allow-list — so a completed registration puts a guardian's national ID and a
minor's date of birth in the same place.

**Aggravating factor: nothing purges it.** `backend/app/retention.py` defines
exactly one sweep, `sweep_anonymous` (`retention.py:49`), and it does not touch
`checkpoints` / `checkpoint_blobs`. No TTL is configured on the checkpointer.

**Note the near-miss that makes this easy to misread.** The codebase *does*
protect PII in the direction it was thinking about — `pii.redact_for_summary`
keeps values out of the rolling summary and therefore out of model prompts
(`app/graph/nodes/safety_out.py`, `app/agents/register/schema.py:24`). The
checkpoint is a different surface and is not covered.

**Impact.** Indefinite retention of minors' identity documents in a table with
no retention policy, no field-level typing, and no redaction on the write path.

**Symptom explained.** None directly — this is not why registration fails. It is
a disclosure risk found while investigating it.

---

## HIGH

### F2 — Lesson turns were cacheable, so lessons replayed without running the graph `FIXED-THIS-SESSION`

**Evidence.** At `HEAD`, `cacheable` excluded card turns, empty replies, and
turns with directives beyond citations/chips — a lesson turn matches none of
those exclusions:

- `backend/app/turn.py:325-343` (HEAD) — no agent-based exclusion
- `backend/app/cache.py:100-107` — the key is `(query, language, persona, account_status, age_band)`; **no learner and no agent**
- `backend/app/api/stream.py:216-225` — the cache is consulted *before the graph is built*; a hit replays and returns

A lesson turn is a state transition, not an answer. A replay serves the prose
and performs none of it: no placement, no `phase` transition to `checking`, no
mastery row. The reader is taught and the machine does not move.

Fixed in the working tree at `backend/app/turn.py:375` (`record.agent in
LESSON_AGENTS`). A re-ingest during this session flushed 76 cached entries.

**Symptom explained.** "The learning agent does not teach; it chats about
money." A replayed cache entry is prose with no lesson behind it.

### F3 — The global system-prompt layer is dead code `HEAD`

**Evidence.** `ASPIRE_SYSTEM_PROMPT` is 5041 characters of product identity and
safety rules — XCD-only, never invent rates, escalate rather than guess. Its
only remaining mentions are comments:

```
app/agent.py:17     "...carried (ASPIRE_SYSTEM_PROMPT ...) is [replaced]"
app/cache.py:375    a token-count comment
```

A repo-wide search for a *consumer* returns nothing. The same is true of
`SIMPLE_MODE_INSTRUCTIONS`, `GAMES_INSTRUCTIONS` and `ELIGIBILITY_INSTRUCTIONS`.
`app/agent.py:14-20` documents the removal deliberately, but the replacement —
"per-agent prompts inside the subgraphs" — reproduces only the AGENT ROLE layer.

**Impact.** No live agent receives the global safety rules. Each agent prompt
independently re-derives (or omits) them. See `diagnosis/prompts/` for the full
per-layer breakdown.

### F4 — No agent LLM call includes conversation history `HEAD`

**Evidence.** Every message-construction site builds `[System, Human]` from
scratch. Full audit in `diagnosis/MESSAGES.md`; the agent-facing ones are:

- `app/agents/qa/nodes.py:495` — `[SystemMessage(system+audience), HumanMessage(question)]`
- `app/agents/learn/teach.py:306` — `[SystemMessage(prompt), HumanMessage(user)]` `WORKING-TREE`
- `app/graph/nodes/classify.py:510` — `[SystemMessage, HumanMessage]` (correct for a router)

`app/memory.py:123` defines `build_prompt`, which assembles summary preface +
history + knowledge context + question — exactly the missing layering. It has
**no caller in `app/`**; the only reference outside comments is
`tests/test_kb_injection.py:120`.

**Partial mitigation.** QA compensates with `rewrite_query`
(`app/agents/qa/nodes.py:86-125`), which resolves pronouns against the last few
turns before embedding. That is why QA tolerates follow-ups despite having no
history at its generation call — and is a plausible reason QA "behaves well"
while the others do not.

### F5 — Escalation is dominated by the grounding floor; there is no graceful decline `HEAD`

**Evidence — static.** `make_ground_check` (`app/agents/qa/nodes.py:626-772`)
has six escalating exits and one non-escalating aside:

| Exit | line | outcome |
| --- | --- | --- |
| small-talk aside | 642 | answered |
| `no_context` | 649 | escalate |
| `below_relevance_floor` (dense) | 668 | escalate |
| `below_relevance_floor` (lexical) | 690 | escalate |
| `unattributed_figure` | 705 | escalate |
| `uncited` | 733 | escalate |
| `invented_citation` | 743 | escalate |
| grounded | 763 | answered |

Floors: `qa_relevance_floor = 0.55` (`app/config.py:303`), `qa_coverage_floor =
0.25` (`app/config.py:311`).

**Evidence — production.** Read-only aggregate over the live `tickets` table
(58 rows):

```
by category    general 32 | knowledge_gap 26
by age_band    adult 47 | 9-12 7 | 16-18 3 | 5-8 1
summaries mentioning the relevance floor:  23 of 58   (~40%)
```

**No repeated-failure counter exists.** Nothing counts consecutive
escalations per session or per intent; each turn decides independently.

**Symptom explained.** "The escalation agent fires far too readily." Two in five
escalations are a retrieval score, not a person asking for a person.

### F6 — Registration intent had no handler for personas without a register agent `FIXED-THIS-SESSION`

**Evidence.** Reproduced from a real ticket raised by the maintainer during this
session, `ASP-6E46F9CB`, `age_band 16-18`:

```
i want to register my child -- The closest chunk scored 0.519, below the 0.550 floor.
```

Path: `classify` → `qa_agent` → `ground_check` → `_escalate` → ticket. Measured
retrieval for that exact string: best chunk `ASP-062` at **0.519** against a
**0.550** floor.

Rewriting the corpus row to close the gap was tried and measured, and is a net
regression (0.519→0.539, still under floor, while degrading two other queries).
The input is an *intent*, not a question; a retrieval floor is the wrong
instrument. Addressed in the working tree by a deterministic matcher ahead of
the classifier (`app/graph/nodes/cards.py:_registration_help`).

**Symptom explained.** Contributes to both "registration fails to complete" and
"escalation fires too readily".

---

## MEDIUM

### F7 — Two curriculum stores; the database one is vestigial `HEAD`

`load_all()` reads YAML (`app/curriculum/schema.py:316-341`, `CONTENT_DIR =
app/curriculum/content`), which holds **1 module, 5 lessons, 5 concepts**. The
database has a parallel schema that is mostly empty:

```
concepts 5 | lessons 0 | modules 1 | concept_widgets 0 | review_events 0
mastery 2  | learners 2 | documents 706
```

The DB `concepts` ids (`budget, goal, need, save, spend`) match the YAML, so the
table exists to give `mastery.concept_id` a foreign key. `lessons` being empty
while YAML has five is the drift worth noting: anything reading lessons from the
database sees a curriculum with nothing in it.

### F8 — Two state fields are written and never read `HEAD`

- `escalation_priority` — 1 write, 0 reads (`app/graph/state.py:277`)
- `speak` — 4 writes, 0 reads in `app/` (`app/graph/state.py:291`, set from
  age band in `initial_state` at `state.py:345`)

`speak` may be consumed by the frontend; I did not audit the client. Reported as
"no reader in `app/`", not as dead.

---

## LOW

### F9 — The learning agent grounds against the FAQ corpus `WORKING-TREE`

`app/agents/learn/graph.py:_retrieve` searches `documents` (706 FAQ rows), the
same corpus QA uses. This is by design — the chunks are framed as background,
never quoted — but it means there is no teaching-specific corpus. At `HEAD` the
learning agent performed no retrieval at all.

---

## What I could not determine

- **A8 live traces (T1–T7): NOT RUN.** The rules require DB writes to go to a
  Neon branch, never primary. There is no `NEON_API_KEY`, no branch URL, and no
  `neonctl` on this machine, and I cannot demonstrate that the configured
  endpoint (`ep-wispy-wave-…-pooler`) is a non-primary branch. T1–T3 write
  guardian PII and T7 can open a ticket. **To unblock:** a branch connection
  string exported as `DATABASE_URL`, plus confirmation it is not primary.
  Running with `DATABASE_URL` unset is not a substitute — it disables the
  checkpointer (no `interrupt()`/resume, so T1/T2 are impossible) and empties
  the retrieval corpus, which would make every QA trace escalate for the wrong
  reason.
- **Ticket attribution.** The `tickets` table has no `persona` column, so the
  child-band grounding escalations cannot be attributed to a specific persona or
  agent. See PREDICTIONS.md P1.
- **A4 `thread_id` across `interrupt()`/resume.** Statically, `thread_id =
  session_id` (`app/graph/checkpointer.py:3`). Proving stability across an
  upload boundary needs the live run above; I have no observed values.
