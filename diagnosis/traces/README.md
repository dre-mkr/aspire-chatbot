# A8 — live traces: NOT RUN (blocked)

**No traces exist in this directory.** T1-T7 were not run, and no instrumentation was added,
so there is nothing to revert.

## Why

Rule 5: "Any DB writes go to a Neon branch, never the primary." I could not obtain a branch:

- `neonctl` / `neon` CLI: **not installed** (`command -v` for both returns nothing).
- No Neon API key or branch DSN in the environment or `.env` (grep for `NEON_*`,
  `DATABASE_URL_(TEST|BRANCH|DEV)`: no matches).
- The configured `DATABASE_URL` host is `ep-wispy-wave-ayny4onp-pooler.c-5.us-east-2.aws.neon.tech`
  — the **primary** pooled endpoint, and the same one the running app writes to.

T1-T7 all write: `applications` and `application_pii` (T1-T3), `tickets` (any escalation),
`mastery` / `review_events` (T4, T5, T7), plus `messages`, `conversations` and
`checkpoints` / `checkpoint_blobs` on every turn. Running them against the configured DSN
would write to primary, so I stopped rather than break the rule.

Read-only `SELECT`s **were** run — permitted, since the rule restricts writes. Those produced
the row counts used in the findings: `documents=706, concepts=5, lessons=0, mastery=2,
concept_widgets=0, applications=6, tickets=58`.

## What I need to unblock it

Either of:

1. A Neon **branch** connection string to put in `DATABASE_URL` (pooled endpoint, and
   `alembic upgrade head` run against it — migration 0001 installs pgvector per database), or
2. `NEON_API_KEY` + the project id, and permission to create/delete a branch myself.

Plus, to keep the run faithful to the rules:

- `VOICE_ENABLED=false` so no ElevenLabs/TTS call is made (the setting is not named
  `voice_enabled` on `Settings` — the exact key needs confirming before the run).
- Session tokens for four personas (Stella 5-8 or 9-12, Orion, Aurora guardian, Nova) plus one
  anonymous session. T1-T3 need an Aurora **guardian** token, since `_AURORA` is the only
  access row that reaches `register_agent`.

## What stays UNDETERMINED without it

- **P5** — whether `thread_id` is stable across the `interrupt()`/resume boundary. Statically
  it is `session_id` throughout, one thread per session
  (`checkpointer.py:367-378`, called at `stream.py:240`), and I found no code path that
  changes it. But the task asks for **observed** `thread_id` values either side of a file
  upload, and I have none. The mechanism that would break resume is instead the parent
  checkpointer being `None` (addendum, final section) — testable only live.
- **P9** — whether the receiving agent re-asks facts already collected after a
  `goto` handoff. `qa/tools.py:308` passes only `active_agent`, so the payload is thin; whether
  that causes a re-ask is behavioural.
- Router decisions and `retrieval_max_score` distributions per persona (T6 was to be the
  healthy control group).
- **T7** specifically — a bare `"4"` from Stella. Static reading says it cannot reach
  `ground_check` (Stella has no QA agent at all, `access.py:91`), so the interesting question
  is whether the classifier sends it to `learn_agent` or `escalate_agent`. That is exactly the
  behaviour A-01 predicts and exactly what a trace would settle.
