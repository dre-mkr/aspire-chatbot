# REPAIR-REPORT

Repairs against `diagnosis/FINDINGS.md` and `diagnosis/FINDINGS-addendum.md`.
Nothing is committed, so the "commit" column names the working-tree change.

## Status of the five tracks

| Track | State | Note |
| --- | --- | --- |
| **E** — escalation contract | **complete** | 5 of 6 items implemented; E.3 was already true |
| **C** — SessionContext & handoffs | **complete except QA migration** | awaiting a decision on touching the protected agent |
| **R** — registration | **R.2 complete (the CRITICAL fix); R.1 already true; R.3–R.5 deferred** | R.3–R.5 acceptance needs a live DB |
| **L** — learning | **deferred** | see "Why L is deferred" |
| **P** — prompt layering | **P.1 complete; P.2 deferred** | P.2 is the T1–T7 regression suite |

## Findings ledger

| ID | Severity | Verdict | Change |
| --- | --- | --- | --- |
| **F1** | CRITICAL | **FIXED** | `register/graph.py:_persist_state` no longer emits `values`. The checkpoint carries a presence map of slot PATHS plus five scalars. Values were already Fernet-encrypted in `application_pii` and reconstructable via `store.load_draft`, so the checkpoint copy was redundant as well as dangerous. `review` became async and loads real values through `load_real_values`. Asserted by `tests/register/test_no_pii_in_checkpoint.py` (19 tests) against the SERIALISED form, since that is what the blob table stores. |
| **F2** | HIGH | **FIXED** (earlier session) | `turn.py:cacheable` refuses `LESSON_AGENTS`. A cache hit returns before the graph is built, so a replayed lesson served prose and performed no placement, phase change or mastery write. `tests/test_cacheable.py`. |
| **F3** | HIGH | **FIXED** | `app/prompting/global_rules.py` revives the 5041-character global layer that had no consumer. Retrieval-specific sections stayed with the Q&A role deliberately. `LOAD_BEARING` pins six safety clauses against reflowing. |
| **F4** | HIGH | **PARTIALLY FIXED** | `app/prompting/builder.py` is now the one construction path and supplies summary + last 6 turns + date. The learn agent is migrated and receives history for the first time. **QA is not migrated** — see "Open decision". `memory.build_prompt` remains orphaned; the builder supersedes it rather than reusing it. |
| **F5** | HIGH | **FIXED** | `ground_check`'s six ungrounded exits now decline (`agents/escalation/decline.py`) and escalate only after 3 unresolved turns on one intent (`counter.py`, which wires up the dead `CLARIFICATION_LIMIT`). Measured: 20 out-of-KB questions that opened tickets now decline, with 0 hallucinations served. |
| **F6** | HIGH | **FIXED** (earlier session) | Registration intent from a persona with no register agent is answered by `cards._registration_help` ahead of the router. |
| **F7** | MEDIUM | **REFUTED as a defect** | Two curriculum stores exist, but the YAML is the live one and the DB `concepts` table (5 rows) exists to give `mastery.concept_id` a foreign key. `lessons` being empty is drift, not breakage — nothing reads lessons from the database. No change. |
| **F8** | MEDIUM | **DEFERRED** | `escalation_priority` (1 write, 0 reads) and `speak` (4 writes, 0 reads in `app/`) are untouched. `speak` may be read by the frontend, which I did not audit, and deleting a field on that basis would be guessing. |
| **F9** | LOW | **ACCEPTED** | The learn agent grounds against the FAQ corpus by design; chunks are background, never quoted. |
| **A-01** | HIGH | **IMPROVED** | For 5-12 the router's option space was "teach" or "human". After E.2 it is "teach" alone, and reaching a person is three explicit paths instead of a routing guess. |
| **A-02** | MEDIUM | **DEFERRED** | `streak` read-never-written, untouched. |
| **A-03** | MEDIUM | **DEFERRED** | `servicing_agent` is still a stub granted to two personas. |
| **A-04** | MEDIUM | **FIXED** | `CLARIFICATION_LIMIT` is read by `counter.LIMIT`; the three-strike rule its comment described now exists. |
| **A-05** | MEDIUM | **DEFERRED** | The audience filter is untouched — it is inside the protected agent. |
| **A-06** | LOW | **DEFERRED** | Stale corpus-size comments (338 vs 706). |
| **A-07** | LOW | **FIXED** | `builder._turn_context` puts today's date in every prompt. No prompt had it. |
| **A-08** | LOW | **FIXED** | A cacheable prefix exists: 4021 bytes bare, byte-identical across turns, verified. |
| **A-09** | LOW | **DEFERRED** | `device_id` redundancy, untouched. |
| **A-10** | decision | **RESOLVED** | Staff registration removed; the KB now separates the programme rule from the channel. |

## Regressions I introduced and then fixed

Recorded because each was live in the tree at some point and each was caught by a
test rather than by review.

1. **E.2 severed four escalation intents.** "put me through to a member of staff",
   "i need someone to call me", "i want a manager", "i need to escalate this" were
   caught by nothing after the router lost its catch-all. Found by
   `test_routing_accuracy_against_the_labelled_set`. Fixed by widening
   `wants_human` and adding the `COMPLAINT` detector, which the enum had without
   any producer.
2. **Complaint precedence was backwards.** `COMPLAINT` triages high, and checking
   `wants_human` first downgraded every complaint that named a person.
3. **A decline recorded no gate identity**, so nothing could tell a figure failure
   from a citation failure. Added `safety_flags["declined"]`.
4. **The streak was not reset on escalation**, so turn 4 on the same intent opened
   a second ticket, and turn 5 a third.
5. **`do_not_reask` wrote a sentinel into `draft.values`** to step past a barred
   slot — which `_persist_state` would have checkpointed and `submit` would have
   sent as a real answer. Moved into `next_missing(barred=…)`.
6. **`SessionContext.mastery` claimed 0.0–1.0 and enforced nothing**; the raw
   integer scale passed straight through, making every mastery threshold true.
7. **`teach._cap` applied the 13-15 word allowance (120) to 9-12 learners** whose
   cap is 70. Found while consolidating eight copies of one band default.

## The eval metric I had to correct

`ungrounded_answers_served` was `if command.goto != "escalate_agent"` — it equated
"did not fetch a human" with "served a hallucination". Those were the same thing
while QA had two outcomes; E.4 added a third, so all 20 out-of-KB rows read as
served and the gate failed on the change it was asked for.

I verified first that the model's invented rate and figure are genuinely
discarded and replaced by the decline copy, then changed the metric to look for
those tokens in the reply. It measures the property its name claims now, and
`ungrounded_declined_gracefully` is the number the change was made to move.

## Open decision

**Migrating QA to the shared builder.** QA puts retrieved chunks in its system
block (`qa/nodes.py:485`), so its prefix has never been the same twice and has
never been cacheable — on the agent that makes the most calls. Moving them to the
human turn is the largest cache win available and is also a change to the prompt
of the one agent the global constraints protect, whose `ground_check` gates on
the model citing rows from that block. Recommended: migrate, gate on `make eval`
grounding metrics, revert if they move.

## Why L is deferred

Not for lack of time. Track L.1 says to create a concepts table, and one exists
with 5 rows backed by a 5-lesson YAML curriculum — so the instruction as written
would fork the content model rather than fill a gap. Worse, L.1 asks for 8–12
seeded concepts of children's financial-education content for a government
programme. The instruction itself says to flag anything authored for review, and
authoring the majority of a curriculum is not something to do unreviewed in the
same pass that rewires the graph. L.2 and L.3 are also largely already true:
mastery is read and written (`learn/graph.py:426`) and the pedagogical move is
chosen in Python, not by the model.

What L genuinely needs, and does not have, is the per-concept `explanation`,
`common_misconception`, `check_questions` and `worked_example` fields on real
content. That is a content task with a review gate, not a code task.

## Not verifiable in this environment

T1–T7 never ran, in either phase. No `NEON_API_KEY`, no branch DSN, no
`neonctl`; T1–T3 write guardian and child PII. That blocks:

- every acceptance criterion of R.3–R.5 and P.2
- Track C's T5 pronoun follow-up and prompt-cache read rate
- the before/after node paths and escalation counts requested per track

`diagnosis/traces/README.md` lists the four steps to unblock it.

## Instrumentation

**None was added, so none needed removing.** The Phase A A8 instrumentation was
never written — the traces it would have served were blocked before it was
needed. What did land permanently is `safety_flags["declined"]`, which is
structured telemetry rather than temporary logging: it records which gate
declined a turn, which the eval harness now counts.
