# A2 — Message construction audit

> **Provenance.** Read against a dirty tree (17 modified + 6 new vs HEAD `c0f9d62`).
> `app/agents/learn/teach.py` **does not exist at HEAD** — it is new this session — so every
> row citing `teach.py` describes code the maintainer is **not** running. All other files cited
> here (`qa/nodes.py`, `classify.py`, `memory.py`, `doc_check.py`, `stream.py`, `main_graph.py`)
> are byte-identical to HEAD, verified per file. See `FINDINGS-addendum.md`.

Every site in `app/` that builds a message list for an LLM call. Found by
`grep -rn "SystemMessage(" app/` (7 sites) plus the injected `invoke` wrappers.

## 1. `qa_agent` — answer generation
- **file:line** `app/agents/qa/nodes.py:494-496`
- **Shape** `[SystemMessage(GENERATE_SYSTEM.format(context=chunks) + "\n" + audience), HumanMessage(question)]`
- **History** **NONE.** Built from scratch each turn.
- **Chunks** in the **SYSTEM** block (`nodes.py:485`, template at `nodes.py:446-459`).
- **Cache-eligible prefix?** **No.** The system block's first line is fixed, but `{context}`
  is interpolated *inside* it (`nodes.py:457-458`) and the `audience` line is appended after
  it (`nodes.py:495`). Since retrieved chunks change per question, the entire system block
  differs every turn — there is no stable prefix for a provider cache to hit.
- ⚠ **Flagged: constructs from scratch without prior turns.**

## 2. `qa_agent` — query rewrite
- **file:line** `app/agents/qa/nodes.py:115`
- **Shape** `invoke(REWRITE_SYSTEM, "{context}\n\nuser: {original}")` → `classify.default_invoke`
  → `[SystemMessage(system), HumanMessage(user)]` (`classify.py:510`)
- **History** **YES — the only agent call that gets any.** 4 turns
  (`REWRITE_WINDOW = 4`, `nodes.py:83`), sliced at `nodes.py:112` as
  `messages[-(REWRITE_WINDOW+1):-1]`, rendered `role: text`.
- **Chunks** n/a (runs before retrieval).
- **Cache-eligible prefix?** System is byte-identical (a module constant); the human turn
  varies. Prefix-cacheable in principle.

## 3. `learn_agent` — teach / reteach
- **file:line** `app/agents/learn/teach.py:306` (both `teach` and `reteach` via `_compose`)
- **Shape** `[SystemMessage(formatted _SYSTEM or _RETEACH_SYSTEM), HumanMessage(user)]`
- **History** **NONE.** The only cross-turn signals are `recent_openings` (last 3 opening
  lines, `teach.py:225-233`) and the boolean `concept_seen_before` (`teach.py:235`) — both
  folded into the *system* block as "do not repeat these", not as dialogue.
- **Chunks** in the **SYSTEM** block, explicitly framed as background not to quote
  (`teach.py:196-201`).
- **Cache-eligible prefix?** **No.** `{spine}`, `{example}`, `{grounding}`, `{ladder}`,
  `{banned}`, `{avoid}` are all interpolated into one template (`teach.py:293-301`), so the
  block varies per lesson, per band and per learner history.
- ⚠ **Flagged: constructs from scratch without prior turns.**

## 4. `register_agent` — document check (vision)
- **file:line** `app/agents/register/nodes/doc_check.py:350-359`
- **Shape** `[SystemMessage(system), HumanMessage([{text: context}, {image_url: …}])]`
- **History** **NONE** — correct here; it is a per-image classification, not a conversation.
- **Cache-eligible prefix?** System is a module constant (`doc_check.py:57`); the image
  varies. Prefix-cacheable in principle.

## 5. Classifier (router)
- **file:line** `app/graph/nodes/classify.py:510`, user string built at `classify.py:423-427`
- **Shape** `[SystemMessage(_SYSTEM), HumanMessage("Handlers:…\n\nCurrently handling: …\n\nMessage: …")]`
- **History** **NONE** — one message only. Deliberate containment (`classify.py:1-10`).
- **Cache-eligible prefix?** `_SYSTEM` is a constant (`classify.py:100`). The handler menu is
  in the *human* turn, so the system prefix is byte-identical across all turns — the best
  cache position of any call site here.

## 6. `safety_out` re-prompt
- **file:line** `app/api/stream.py:461-466`
- **Shape** `[SystemMessage(instruction), HumanMessage(text)]`
- **History** NONE — a rewrite of one string; correct.

## 7. `persist` summariser / title
- **file:line** injected `Summariser` (`main_graph.py:179`, called `main_graph.py:212`);
  prompts `SUMMARY_PROMPT` / `TITLE_PROMPT` (`prompts.py:272,241`) via `agent.py:40`.
- **History** redacted message strings only (`main_graph.py:205-209`), redaction *before*
  summarisation.

## Summary of findings

| Call site | History? | Turns | Chunks in |
|---|---|---|---|
| qa.generate | **No** | 0 | SYSTEM |
| qa.rewrite_query | Yes | 4 | n/a |
| learn.teach / reteach | **No** | 0 | SYSTEM |
| register.doc_check | No (correct) | 0 | n/a |
| classifier | No (by design) | 0 | n/a |
| safety_out reprompt | No (correct) | 0 | n/a |

**Two agent call sites build their message list from scratch and drop all prior turns:**
`qa/nodes.py:494` and `teach.py:306`. Neither receives `messages` and neither receives
`summary`.

**The assembler that would have done this exists and is unused.** `app/memory.py:130`
`build_prompt` assembles `SystemMessage(SUMMARY_PREFACE + summary)` followed by the recent
window (`memory.py:145-149`) — exactly the missing layer. Its only importers are
`scripts/measure_prompt_tokens.py:36` and two test modules. No graph node imports it.

**Prompt-cache eligibility is poor by construction.** The two expensive calls (generate,
teach) interpolate volatile content into the middle of their system block. Moving the fixed
rules above the volatile `{context}` / `{spine}` would make a stable prefix possible; today
there is none.
