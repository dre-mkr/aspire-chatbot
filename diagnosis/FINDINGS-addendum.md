# FINDINGS — addendum (second, independent pass)

`FINDINGS.md` and `PREDICTIONS.md` in this directory were authored by an earlier run and are
**left untouched**. This file records only what a second pass adds or corrects. Where we
agree, the earlier document is the better-evidenced of the two (it ran a live read-only probe
of `checkpoint_blobs`; I reached the same conclusion statically).

## Provenance — and a correction to my own pass

The earlier document's provenance warning is **accurate and I initially missed it.** The tree
is dirty: 17 modified + 6 new files vs `c0f9d62` (current HEAD). It was clean when I checked
immediately after merging, and changed underneath me mid-analysis, so part of my reading was
of working-tree code presented as though it were what the maintainer runs.

Verified per-file, so each finding below carries a label:

- `HEAD` — file is byte-identical to `c0f9d62`. Confirmed clean: `qa/nodes.py`,
  `escalate/graph.py`, `prompts.py`, `memory.py`, `register/graph.py`, `register/store.py`,
  `checkpointer.py`, `stream.py`, `classify.py`, `main_graph.py`.
- `WORKING-TREE` — `backend/app/agents/learn/teach.py` **does not exist at HEAD** (untracked,
  new this session). Every claim citing `teach.py` therefore describes code the maintainer is
  **not** running. `access.py`, `learn/graph.py`, `cards.py`, `intents.py`, `safety_out.py`,
  `stream_interceptor.py`, `turn.py` are modified.

Two of my earlier statements need correcting on that basis:

1. **`_NOVA` is `("qa_agent", "escalate_agent")` only in the working tree.** At HEAD it is
   `("qa_agent", "register_agent", "escalate_agent")` (`access.py:121` @ `c0f9d62`) — three
   options, not two. My "escalation is 50% of Nova's option space" claim is working-tree only.
2. **The learning-agent no-history and no-persona-card claims rest on `teach.py`**, which is
   new. At HEAD the learning agent emitted authored YAML teach points and made no model call
   for prose, so "it chats about money" cannot be explained by `teach.py` at HEAD.

**`_STELLA` survives the check**: identical at HEAD (`access.py:91`) and working tree
(`access.py:120`) — `("learn_agent", "escalate_agent")`. That finding stands for HEAD.

---

## Additive findings

### A-01 `HEAD` — HIGH — For ages 5-12 the router's whole option space is "teach" or "human"
`access.py:91` @ HEAD — `_STELLA = ("learn_agent", "escalate_agent")`, applied to bands 5-8
and 9-12. There is **no QA agent of any kind** in the Stella row. The classifier sees only
those two names (`classify.py:424`) and `escalate_agent`'s description explicitly invites
"…the question is **outside what this assistant can answer**" (`classify.py:94-97`).

A plain knowledge question from a child has no correct destination: it either escalates or
lands on the lesson machine, which starts a lesson rather than answering. One cause, two
symptoms (escalation over-fires; the learning agent fields Q&A traffic). Consistent with
`tickets=58` vs `applications=6`. Partial mitigation: `_coerce`'s fallback never selects
`escalate_agent` (`classify.py:181-184`), so this needs the model to actively choose it.

*Not in the earlier document, which treats over-escalation as a QA-path property.*

### A-02 `HEAD` — MEDIUM — `streak` is read, never written, and is not a state field
`learn/graph.py:467-468` @ HEAD reads `state.get("streak")`. `streak` does not appear in
`graph/state.py` at HEAD (grep count 0) and no node writes it. `streak=streak` at
`learn/graph.py:559` is the `ProgressDirective` field, not a state write.

`scheduler.streak_after` therefore always receives 0: streaks never accumulate and
`badge_for_streak` can only award the day-one badge. The wrap-up reports progress that cannot
increase.

### A-03 `HEAD` — MEDIUM — `servicing_agent` is a stub yet granted to two personas
Granted by `_ORION_16_18` and `_AURORA` @ HEAD (`access.py` lines 105/115 in the HEAD file);
no builder is registered, so `_agent_node` returns `make_stub` (`main_graph.py:82,165`). A
correctly-routed account question receives `[servicing_agent is not built yet.]`, then is
gated and persisted as a normal turn.

### A-04 `HEAD` — MEDIUM — The three-strike escalation rule is dead code
`CLARIFICATION_LIMIT = 3` (`escalate/graph.py:89`) is **read nowhere** in `app/` — grep
returns only the definition. The comment above it (`:86-88`) describes an intended
three-failures-in-a-row trigger that was never wired. `"repeated_clarification"`
(`:82`) is a triage label, not a counter. This supplies the file:line behind the earlier
document's "no repeated-failure counter anywhere".

### A-05 `HEAD` — MEDIUM — The audience filter currently filters nothing, and defaults disagree
`AUDIENCE_TAGS` (`qa/nodes.py:368-371`) maps `public` and `youth` to the **same five tags**, so
the two slices are identical — stated candidly in-code at `:363-367`. Separately,
`qa/nodes.py:322` defaults to `"all"` while the learning path defaults to `"youth"`, so the
same question is scoped differently depending on which agent asks. (The learning half of this
is `WORKING-TREE`.)

### A-06 `HEAD` — LOW — Corpus-size reasoning is stale by ~2×
`qa/nodes.py:6,177` reason from "338 rows"; measured `documents = 706`. `bm25_rank` rebuilds
its index per call (`:186`) on a cost argument that assumed half the rows.

### A-07 `HEAD` — LOW — No prompt receives the current date
`current_datetime` reaches no call site (see CONTEXT-MATRIX.md). Deadline questions are
answered with no notion of today.

### A-08 `HEAD` — LOW — Prompt-cache prefixes are unstable by construction
`qa.generate` interpolates `{context}` inside its system block (`nodes.py:457`), so the block
differs every turn and no provider prefix cache can hit. The classifier is the only call site
with a byte-identical system prefix (`classify.py:100`). Moving fixed rules above the volatile
block would make a stable prefix possible.

### A-09 `HEAD` — LOW — `device_id` is redundant in `AspireState`
Written by `hydrate`, never read back off state by any graph node. The value is used outside
the graph (`sessions.py`, `auth.py`, `identity.py`); the state field is not.

### A-10 `HEAD` — worth a decision — staff can reach registration at HEAD
`_NOVA` @ HEAD includes `register_agent` (`access.py:121`), i.e. staff acting on another
person's behalf. The working tree removes it with a written rationale (auth realm + audit
trail). Flagged because it is a live HEAD property, not because the removal is wrong.

---

## Agreements worth restating

Reached independently and matching the earlier document: `ground_check` is confined to the QA
subgraph (constructed only at `qa/graph.py:77`; no other construction site in `app/`), so P1's
mechanism is refuted; a `concepts` table exists (5 rows) distinct from `documents` (706), so
P6 is refuted; mastery has a single real writer at `learn/graph.py` `mastery_update`, so P7 is
refuted; registration's next step is Python (`pick_slot`, `register/graph.py:187`), so P4 is
refuted.

## One verification the earlier document leaves open, now settled

The registration subgraph compiling with `checkpointer=None` (`register/graph.py:696`) is
**not** a bug. LangGraph 1.2.10 documents `None` as "may inherit the parent graph's
checkpointer when used as a subgraph" (`langgraph/graph/state.py:1187`) and injects it at
runtime (`langgraph/pregel/_algo.py:914`). Verified in the installed library rather than
assumed.

The real dependency is on the **parent**: `stream.py:232` passes `await get_checkpointer()`
through with no guard, and that returns `None` in three documented paths — no `DATABASE_URL`
(`checkpointer.py:265`), a Windows Proactor loop (`:281`), and latched pool-open failure
(`:318,327`). LangGraph is explicit that "A checkpointer must be enabled for interrupts to
work!" (`langgraph/types.py`, `interrupt()` docstring). In any of those three states
`interrupt()` cannot resume and registration restarts from the first question — which the
subgraph's own comment predicts (`register/graph.py:691-695`). Bears on P5 and symptom S3.
