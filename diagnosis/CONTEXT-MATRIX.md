# A1 — Context matrix at the LLM call boundary

> **Provenance.** Read against a dirty tree (17 modified + 6 new vs HEAD `c0f9d62`).
> The `learn.teach` column describes `app/agents/learn/teach.py`, which **does not exist at
> HEAD** (new this session); at HEAD the learning agent made no model call for prose. Every
> other column is HEAD-clean, verified per file. See `FINDINGS-addendum.md`.

What each agent's **model call** actually receives. "PRESENT" means it reaches the prompt or
the call's inputs from shared state; "DERIVED" means the agent recomputes it locally;
"ABSENT" means it is not available to that call at all.

Only agents that make a model call have a row. `escalate_agent` makes **no model call**
(`agents/escalate/graph.py` — no `invoke`/`ainvoke`/`SystemMessage` anywhere), so nothing is
in its prompt because there is no prompt; its copy is canned Python (e.g. `graph.py:131`).

| Field | qa.generate<br/>`qa/nodes.py:494` | qa.rewrite_query<br/>`qa/nodes.py:115` | learn.teach<br/>`teach.py:306` | register.doc_check<br/>`doc_check.py:353` | classifier<br/>`classify.py:429` |
|---|---|---|---|---|---|
| persona | **PRESENT** (`nodes.py:488`) | ABSENT | ABSENT | ABSENT | ABSENT (by design) |
| age_band | **PRESENT** (`nodes.py:487`) | ABSENT | **DERIVED** `_band` | ABSENT | ABSENT (by design) |
| locale | **PRESENT** (`nodes.py:489`) | ABSENT | ABSENT¹ | ABSENT | ABSENT (by design) |
| account_status | ABSENT | ABSENT | ABSENT | ABSENT | ABSENT (by design) |
| display_name | **ABSENT everywhere** — no such state field | ABSENT | ABSENT | ABSENT | ABSENT |
| recent_turns | **ABSENT** | **PRESENT** (4 turns, `nodes.py:110-112`) | **ABSENT** | ABSENT | ABSENT (single message) |
| running_summary | **ABSENT** | ABSENT | **ABSENT** | ABSENT | ABSENT |
| mastery / learner state | n/a | n/a | **DERIVED** `learning` dict; mastery rows fetched in `resume_or_place` (`learn/graph.py:112`) | n/a | n/a |
| concepts_seen | n/a | n/a | **DERIVED** `concept_seen_before` (`learn/graph.py:164`), `recent_openings` (`teach.py:225`) | n/a | n/a |
| last_game_result | n/a | n/a | ABSENT from prompt (routes a node, `learn/graph.py:662`) | n/a | n/a |
| open_application_id | n/a | n/a | n/a | **DERIVED** from `registration` draft | ABSENT |
| current_registration_step | n/a | n/a | n/a | **DERIVED** slot walk | ABSENT |
| kb_version | **ABSENT everywhere** — no such field exists in the codebase | ABSENT | ABSENT | ABSENT | ABSENT |
| current_datetime | **ABSENT** | ABSENT | ABSENT | ABSENT | ABSENT |

¹ `locale` reaches the learning turn only via the widget planner argument
(`teach.py:383`), never the teaching prompt. The band vocabulary lists (`ladder`, `banned`,
`teach.py:298-299`) are English regardless of locale.

## DERIVED cells — recomputation sites and disagreement risk

| Cell | Recomputed at | Can it disagree with shared state? |
|---|---|---|
| learn `age_band` | `learn/graph.py:86` `_band()` — `state.get("age_band") or "9-12"` | **Yes.** A missing/unknown band silently becomes `9-12`. `teach.py:338` repeats the same default independently, and `teach.py:270` `_cap()` falls back to `120` when the band is unknown — three separate defaults for one value. |
| learn audience | `teach.py:113-121` `_AUDIENCE` keyed on `active_agent`, default `"youth"` | **Yes**, but fails narrow (safe). Diverges from `qa/nodes.py:322` `_audience`, which defaults to `"all"` — two tables for the same question with opposite fallbacks. |
| learn `concept_seen_before` | `learn/graph.py:164` from mastery rows | No — single read. |
| learn `recent_openings` | `teach.py:225` from checkpointed `learning` | Per-conversation only; documented at `teach.py:204-223`. |
| register step / application id | `register/graph.py` slot walk from `store.Draft` | Authority is the DB draft; consistent. |
| qa audience | `qa/nodes.py:316-325` from `active_agent` | See learn audience above. |

## Consequences worth naming

1. **No agent LLM call receives `running_summary`.** `persist` writes `summary`
   (`main_graph.py:212`) and nothing reads it back into a prompt. The rolling summary is
   computed, PII-redacted, checkpointed — and never used. (F-06)
2. **`qa.generate` and `learn.teach` receive no conversation history at all** (MESSAGES.md).
   For QA this is partly mitigated because `rewrite_query` folds context into `qa_query`,
   but the *answer* call still sees one bare question.
3. **`current_datetime` is absent from every prompt.** Any deadline question is answered
   without knowing today's date.
4. **`account_status` reaches no prompt.** It gates routing via `access.py` only.
5. `display_name` and `kb_version` do not exist anywhere in the codebase — they are not
   merely unwired.
