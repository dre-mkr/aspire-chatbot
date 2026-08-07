# P1–P10 verdicts

Labels as in FINDINGS.md: `HEAD` / `WORKING-TREE` / `FIXED-THIS-SESSION`.

| # | Prediction | Verdict | Evidence |
| --- | --- | --- | --- |
| P1 | Grounding runs on non-QA paths, so learning/registration turns are scored against a knowledge corpus and escalate | **REFUTED** (mechanism) / real effect | `ground_check` is added as a node in exactly one place: `app/agents/qa/graph.py:77`. The learn subgraph's node set is `resume_or_place, plan_widget, teach, check, branch, hint_ladder, reteach, explain_back, mastery_update, wrap_session, widget_result, game_result` (`app/agents/learn/graph.py:614-640`) — no `ground_check`. The register subgraph's is `resume_or_start, route, ask, collect, doc_check, extract, review, submit` (`register/graph.py:665-672`) — no `ground_check`. A learning or registration turn cannot traverse it. |
| P2 | Escalation is reachable as a router destination or fallback edge, not only as an explicit tool call | **CONFIRMED** | Three distinct paths. (a) Router destination: `classify` → `escalate_agent` via `_to_agent`, `app/graph/main_graph.py:404`. (b) Graph handoff from inside QA: `Command(graph=PARENT, goto="escalate_agent")`, `app/agents/qa/nodes.py:1014-1022`. (c) Explicit tool: `app/agents/qa/tools.py:337-339`. Only (c) carries a caller-supplied reason. |
| P3 | There is no third outcome between answering and escalating | **PARTIAL** | There is exactly one: the small-talk aside, `app/agents/qa/nodes.py:640-642`, which returns a reply without escalating. Every other non-grounded exit escalates — six of them (`nodes.py:649, 668, 690, 705, 733, 743`). There is no "I can't answer that, here's what I can do" decline, and no repeated-failure counter anywhere. |
| P4 | The registration next-step decision is made by the LLM rather than by Python | **REFUTED** | Slot selection is `pick_slot(draft)` in Python (`app/agents/register/graph.py:277`), routed by deterministic predicates `_needs_document`, `_after_ask`, `_after_doc_check`, `_after_extract` (`register/graph.py:681-687`). Question text is authored per `Slot` (`register/schema.py:315-420`), not generated. The only model call in the subgraph is the document vision check (`register/nodes/doc_check.py:353`). |
| P5 | `thread_id` is not stable across `interrupt()`/resume, so uploads restart the flow | **UNDETERMINED** | Statically `thread_id = session_id`, one thread per session (`app/graph/checkpointer.py:3`), and `collect` suspends with `interrupt()` at `register/graph.py:287` with the checkpointer declared required at `register/graph.py:691`. I have no observed `thread_id` values because A8 is blocked — see FINDINGS.md "What I could not determine". |
| P6 | No concepts table exists; the learning agent retrieves FAQ rows and therefore answers instead of teaching | **REFUTED** | A `concepts` table exists with 5 rows (`budget, goal, need, save, spend`), alongside `lessons`, `modules`, `concept_prerequisites`, `concept_widgets`, `mastery`, `learners`, `review_events`. The teachable-unit store is the YAML curriculum — 1 module, 5 lessons, 5 concepts (`app/curriculum/schema.py:316`, `CONTENT_DIR`). At `HEAD` the learning agent performed **no retrieval at all**; it emitted authored YAML teach points verbatim (`learn/graph.py:make_teach`, HEAD). The stated cause is wrong. See F2 for what does explain the symptom. |
| P7 | Nothing writes learner mastery state | **REFUTED** | `MasteryStore.record` is a read-apply-write (`app/learning/mastery.py:277-286`), called from `mastery_update` (`app/agents/learn/graph.py:426`), which every branch of the lesson machine reaches. The live table is non-empty: `mastery` 2 rows, `learners` 2 rows. Low counts reflect little real usage, not a missing write path. |
| P8 | The persona card is absent from the registration, learning, and escalation prompts | **PARTIAL — and mostly vacuous** | Registration and escalation generate no prose, so they have no prompt to be missing a card from: registration questions are authored per slot, and the escalation summary is explicitly *not* a model call (`app/agents/escalate/graph.py:187`). The learning prompt does carry a **band** card — vocabulary ladder, banned terms, word cap (`app/agents/learn/teach.py:_SYSTEM`) — but no persona register or local-reference card. QA gets a one-line audience note only (`app/agents/qa/nodes.py:486-489`). The larger finding is F3: the GLOBAL layer is absent from *every* agent, which P8 does not mention. |
| P9 | Handoffs pass control (`goto`) without a payload of established facts | **REFUTED for the escalation handoff** | `_escalate` carries a payload: `escalation_reason`, a PII-redacted `escalation_summary`, `groundedness`, and `safety_flags.ungrounded` with reason and detail (`app/agents/qa/nodes.py:1019-1040`). The QA→register handoff at `app/agents/qa/tools.py:308` passes only `active_agent`, so the narrow version of P9 holds there. **UNDETERMINED** whether the receiving register agent re-asks, because that needs A8. |
| P10 | One or more subgraphs build their message list from scratch, dropping history | **CONFIRMED** | Every agent LLM call is `[System, Human]` with no prior turns: `app/agents/qa/nodes.py:495`, `app/agents/learn/teach.py:306`, `app/graph/nodes/classify.py:510`. `app/memory.py:123` `build_prompt` — which would assemble summary + history + knowledge — has no caller in `app/`. See F4 and MESSAGES.md. |

## Contradicting evidence

Findings that cut against the maintainer's model of the system.

1. **Grounding is structurally confined to QA, yet child-band escalations carry
   grounding reasons.** The live `tickets` table shows `5-8` and `9-12` rows with
   `"Nothing in the knowledge base matched."` and `"The closest chunk scored
   0.465, below the …"`. Under the current access matrix, `stella` (the only
   persona for those bands) reaches `learn_agent` and `escalate_agent` **only** —
   never a QA agent (`app/graph/access.py:120`). So these turns reached QA as
   an anonymous caller (`qa_agent_public` is on the anonymous row,
   `access.py:163-170`) or under an adult persona carrying a child band. This
   looks like P1 and is not P1. **Attribution is UNDETERMINED**: the `tickets`
   table has no `persona` column.

2. **The learning agent at `HEAD` could not have "chatted about money" from its
   own generation, because it did not generate.** It emitted
   `teach_points[band][:2]` plus one example, verbatim from YAML. Any free-form
   money chat a learner saw came from somewhere else — most plausibly a replayed
   cache entry (F2) or a classifier decision routing the turn away from
   `learn_agent` entirely.

3. **Registration is more deterministic than predicted, which relocates the
   bug.** P4 assumed an LLM was choosing steps. It is not — slot order, routing
   and validation are all Python (`register/graph.py:681-687`, Pydantic models at
   `register/schema.py:103-160`). So "frequently fails to complete or loses
   state" is unlikely to be a reasoning failure and more likely a persistence or
   resume failure, which points at P5 — the one prediction I could not test.

4. **QA "behaving well" is partly luck of compensation, not absence of the
   defect.** QA has the same no-history defect as everything else (F4); it
   survives because `rewrite_query` resolves pronouns before embedding
   (`app/agents/qa/nodes.py:86-125`). The healthy control group shares the
   underlying flaw.

5. **P8's premise is inverted.** The persona card is patchy, but the layer that
   is comprehensively missing is the GLOBAL one — 5041 characters of
   XCD-only/never-invent-rates/escalate-vs-guess rules with no consumer (F3).
   Fixing persona cards without restoring that leaves the safety layer absent.
