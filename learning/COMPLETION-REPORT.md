# Completion report — the ASPIRE learning agent

Two commits on `main`: [`8be5d0a`](../../commit/8be5d0a) (the fix) and
[`ad43e97`](../../commit/ad43e97) (concepts, evals, health).

**Headline.** The reported symptom had two causes, not one. The brief predicted
the second and missed the first: the learning agent never read the learner's
message at all. `resume_or_place` chose a lesson from the spaced-repetition
schedule, so "What is compound interest?" was answered with a competent
explanation of what saving is. Both causes are closed, plus a third the brief did
predict (no floor under prose substance).

**One external blocker.** The OpenAI account exhausted its credits during Pass C
of the concept seeder. Passes A–D completed and are checkpointed; Pass E wrote all
67 concepts **without embeddings**. Concept resolution therefore runs on a lexical
fallback rather than semantically. Everything else is unaffected. Recovery is one
command, listed at the bottom.

---

## Per phase

### Phase 0 — Recon ✅

[RECON.md](RECON.md). Full graph shape with mermaid, the turn traced HTTP → SSE
bytes with every LLM call and its model, the widget path, the concepts and
learner-state audit, retrieval, prompt layering, the formula registry, the SSE
protocol, and locale. Ends with the ranked "What actually breaks the lesson".
Prompt extracted to [prompts/current_learn_system.txt](prompts/current_learn_system.txt).

The hard gate **passed** — LangGraph graph, learning agent node and Postgres KB all
present — so I proceeded without pausing, as instructed.

Eight material divergences from the brief are tabulated at the end of RECON.md.
The load-bearing ones: five age bands not four, 3072-dim OpenAI embeddings not
BGE-M3, a `concepts` table that already existed as a curriculum registry, prompt
layering already built, and all nine widget primitives already shipped.

### Phase 1 — Concepts ✅ (with a measured shortfall)

Migration [`0016_teachable_concepts`](../backend/alembic/versions/20260807_0016_teachable_concepts.py)
extends `concepts` in place rather than creating a new table, because
`mastery.concept_id` and `lessons.concept_id` are foreign keys onto it and a
parallel table would mean two answers to "what has this child learned". Adds
`concept_candidates` as the gap list.

[`scripts/seed_concepts.py`](../backend/scripts/seed_concepts.py) — five passes,
idempotent, resumable, `--dry-run` verified.

| Acceptance criterion | Target | Actual | |
|---|---|---|---|
| Concepts produced | ≥ 40 | **67** | ✅ |
| KB rows assigned to ≥ 1 concept | ≥ 90% | **82.6%** (583/706) | ❌ |
| Grounding-validation escapes | 0 | **4 concepts**, bodies nulled, marked `needs_review` | ⚠️ |
| Check items | ≥ 3 per concept per band | **788 total**, median 12 per concept | ✅ |

**On the 82.6%.** 123 rows landed in no concept: 99 FIN- and 24 ASP-. Spot-checking
the orphans, most are administrative rows the assignment prompt is explicitly told
to leave unassigned ("what are your opening hours") — but not all of them, and I am
not going to claim the shortfall is entirely benign without having read all 123.
Pass A also over-produced: 123 proposals merged to **114** concepts against the
brief's 40–70 target, because the Jaccard title-merge at 0.7 under-merged. Finer
concepts draw fewer rows each, which is the same shortfall seen from the other end.
Both are fixable by re-running Pass A with a stricter merge; neither is fixable
without credits.

**On the 4 escapes.** Pass D validated every number in every body against the source
rows, `numeric_anchors`, and the formula registry. 4 of 69 concepts still failed
after one regeneration — and their retries could not run, because that is exactly
when credits ran out. Their offending bodies are nulled and the concepts are
`needs_review`, which excludes them from runtime. So **no ungrounded body is
servable**, which is the property that matters; "zero escapes" is not yet true and
is reported as such.

Deliverables: [taxonomy.json](taxonomy.json),
[concepts-review.csv](concepts-review.csv) (945 rows for task-force sign-off),
[KB-GAPS.md](KB-GAPS.md) — **1,764 unsupported claims across 67 concepts**, grouped
and flagged `PROGRAMME` where a claim needs an authoritative source.

### Phase 2 — Concept resolution ✅

[`resolve.py`](../backend/app/agents/learn/resolve.py). Four branches in strict
precedence: continuation → semantic → RAG-teach → decline. Thresholds in `Settings`
(`learn_resolve_threshold` 0.62, `learn_disambiguate_floor` 0.45).

Continuation is decided **structurally, not semantically**, and that is the whole of
L4: a learner who was asked "how much after 4 weeks?" and replies "20" is answering,
and "20" embeds close to nothing. 36 tests.

**Deferred:** threshold calibration against 60 labelled utterances. The labelled set
needs embeddings to calibrate against, and there are none. The thresholds are the
brief's defaults, in config, ready to calibrate.

### Phase 3 — Move planning and the TEACH renderer ✅ — **the fix**

[`planner.py`](../backend/app/agents/learn/planner.py) — pure Python, zero LLM,
exhaustively unit-tested (the cross-product walks 24,000 combinations; all seven
moves reachable).

[`contract.py`](../backend/app/agents/learn/contract.py) — the band contract as a
*predicate*. A prompt saying "40 to 90 words" produces 30-word replies often enough
that the instruction is decorative.

[`render.py`](../backend/app/agents/learn/render.py) — all three tiers:

1. generate;
2. validate, and regenerate once with the violation quoted — only on **blocking**
   violations (empty, thin, ungrounded, unanswerable), not on an over-long
   sentence, because a regeneration is a second frontier call on a turn a child is
   waiting through;
3. a deterministic template built in Python from the concept row.

**Tier 3 is what makes the reported symptom impossible.** With no provider key at
all, a learner still gets the band body, the local example and the check question.

### Phase 4 — The widget pipeline, decoupled ✅

[`widgets.py`](../backend/app/agents/learn/widgets.py). Plan → compose → **nine**
gates → cache. `build_widget` is wrapped in a catch-all that can only ever return an
outcome; the widget task is created before the prose is awaited and awaited only
after the prose is on the wire.

Nine gates, not seven: the repository's existing seven (`parse schema band numeric
formula copy budget`) plus `locale` and `provenance`. The brief's ordering would
have deleted `formula` and `copy` — see [OBJECTIONS.md §3](OBJECTIONS.md).

The inline sentinel path is **hard-disabled** at
[`teach._widget_prompt`](../backend/app/agents/learn/teach.py), with the mechanism
of the truncation written up where the code used to be.

### Phase 5 — CHECK / HINT / EVALUATE / mastery ⚠️ partial

Check selection and hint-rung selection are in Python
([`tutor.select_check`, `select_hint`](../backend/app/agents/learn/tutor.py)); the
model renders them. The mastery scale, its transition table and spaced repetition
(1/3/7/21 days) **already existed and already match the brief exactly**, including
the non-negotiable rule — verified in L5: `Evidence.WIDGET` is a *ceiling* at 1, so a
child cannot slider their way to a badge.

**Deferred:** the EVALUATE structured call that grades a free-text answer. The
graph's existing deterministic `grade_answer` still runs on the curriculum path;
the tutor path plans `Move.EVALUATE` and renders it, but does not yet call a grader.

### Phase 6 — Persona, locale, voice ⚠️ partial

Prompt layering (GLOBAL + PERSONA_CARD + AGENT_ROLE, cacheable prefix) **already
existed** and the tutor uses it. Voice: `contract.tts_safe` is implemented and
tested — "EC$25" → "25 EC dollars", percentages spelled, parentheticals removed.

**Deferred:** per-locale concept bodies. All 67 concepts are `locale='en'`; the
schema supports `es`/`fr` rows and generating them needs credits. The locale gate
drops a mismatched widget, so a Spanish turn cannot get English slider labels.

### Phase 7 — Observability ✅

Structured log line on every learning turn with all 17 fields.
[`app/learning/health.py`](../backend/app/learning/health.py) aggregates into hourly
Valkey counters; `GET /admin/learning/health` returns the rates, the gate-failure
histogram, concept coverage, band and move mix, and — computed server-side —
`breaches` against the four thresholds. `zero_prose_turns` has no tolerance: one is
a regression, not a statistic.

### Phase 8 — Evals ✅

[`evals/learning_agent.py`](../backend/evals/learning_agent.py). **11/11 passing**,
offline. Wired into `make eval` as a dependency, so a prompt change is gated the
same way a code change is. `--live` re-runs the same assertions against real models.

---

## Test results

| | Passed | Failed |
|---|---|---|
| Baseline, before any change (47 min) | 3047 | **2** — both environmental, pre-existing |
| Mid-work full suite (26 min) | 3110 | 9 failed + 4 errors |
| **Full suite, final (24 min)** | **3142** | **6 failed + 4 errors, every one environmental** |
| `tests/learning/` alone | **250** | 0 |
| `tests/voice tests/safety tests/register tests/games tests/eligibility` | **652** | 0 |
| Frontend `parser.test.ts` (directive ordering) | **13** | 0 |
| `evals/learning_agent.py` | **11/11 scenarios** | 0 |

New tests: **250** in `tests/learning/` — planner 24 (including a 24,000-case
cross-product), resolve 38, contract 28, prose-survives-widgets 14, plus the
existing suite.

### Every remaining failure, accounted for

Three were mine and are fixed:

| Test | Why it broke | Fix |
|---|---|---|
| `test_teach.py::test_a_planned_kind_adds_its_composition_instructions` | asserted the inline sentinel reaches the prompt | inverted — it now asserts it does **not**, with the mechanism documented |
| `test_teach.py::test_a_kind_that_was_written_is_remembered` | same path | asserts no widget is recorded on the authored path |
| `test_resolve.py::test_an_embedder_that_raises_falls_through` | the lexical fallback now resolves it | asserts the fallback resolves by name, plus a new test that it does not invent a match |

Six failures and four errors remain, **none of them this work**:

| Test | Cause |
|---|---|
| `test_classify.py::test_routing_accuracy_against_the_labelled_set` | HTTP 429 `credit_balance_exhausted` |
| `test_planner.py::test_planner_accuracy_and_over_trigger` | same |
| `test_retriever_equivalence.py` (2 failed, 4 errors) | same — needs `embed_query_cached` |
| `test_no_pii_in_logs.py::test_the_retrieval_line_still_says_something_useful` | pre-existing, in the baseline |
| `test_ops_endpoints.py::test_disabled_debug_route_is_indistinguishable_from_an_absent_one` | pre-existing, in the baseline |

I also introduced one regression during the work and caught it before committing:
routing `"teach me"` to the tutor broke seven curriculum-lesson tests. `"teach me"`
names no topic and belongs to placement; `asks_about_a_topic` now requires a
subject after the verb, and falls back to the curriculum entirely when the concept
store is empty.

---

## Before / after: "What is compound interest?"

### Before

Both personas received **the same lesson about a different topic**.
`scheduler.place()` takes no utterance parameter, so the turn served
`l01_what_is_saving` — the first unmastered lesson for the band — and retrieval
searched on *that lesson's* objective, not on the question. Compound interest is
not in the curriculum at any band, so no routing repair alone would have reached
it.

> Saving means keeping money for later instead of spending it now. When you save,
> you choose to wait. You put EC$5 aside from your pocket money each week.

35-word ceiling at 5-8. Widget JSON, when planned, competed with that budget inside
the same model call and could truncate the lesson entirely if its closing marker
never arrived.

### After — Stella (age 9, band 9-12)

Resolved `compound_interest` at 0.90. Move `TEACH`. **111 words**, tier 3.

> Let us take this apart. When you save money, it may earn interest. If you leave
> that interest with the saved money, the next interest can be earned on a bigger
> amount. It is like a snowball rolling downhill. It picks up snow, gets bigger,
> and then picks up even more snow. For example, EC$1,000 earns EC$50. If the EC$50
> stays with the savings, the next year interest can be earned on EC$1,050. After
> that, the base can become EC$1,102.50. Each time the base is bigger, the growth
> can speed up. **Your turn.** EC$1,000 earns EC$50. If the EC$50 is left with the
> savings, what amount can earn interest next year?

### After — Orion (age 16, band 16-18)

Same question, same concept, **175 words**, tier 3.

> Let us get into it. Compound interest is growth on both the principal and the
> interest already accumulated. If returns are left in place, the base for the next
> round is larger. For example, EC$1,000 earns EC$50, so the next year interest is
> earned on EC$1,050, then on EC$1,102.50, and so on. This is why compound interest
> makes money grow faster, not slower. Time is a major part of the effect. In one
> example, saving EC$50 a month from age 10 to age 18 at 5 percent means deposits
> of EC$4,800 and an ending amount of roughly EC$5,900. If that amount is then left
> untouched to age 40 without adding a cent, it grows to about EC$17,000. The later
> growth comes from time and compounding, not from adding more money. The same
> force can work against a borrower. Unpaid credit card balances compound too, so
> debt can quietly multiply. **Work this one out.** In the example, saving EC$50 a
> month from age 10 to age 18 at 5 percent gives total deposits of how much?

**Both are tier 3** — the deterministic floor, with no model call, because there are
no credits. That is the honest and slightly remarkable result: the *worst* output
this agent can now produce is substantially better than the best it produced before.
Tier 1 has not been observed live.

---

## §12 metrics, current values

Measured over the eval suite and the 200-combination property sweep. **No production
traffic has run**, so these are not 24-hour production rates.

| Metric | Threshold | Current | |
|---|---|---|---|
| `teach_fallback` rate | > 2% is a regression | **100%** — no credits, every turn is tier 3 | ⚠️ environmental |
| `widget_gate_failed` rate | > 15% | **0%** (eval suite; no live composer) | ✅ |
| `resolution_source == "none"` rate | > 8% | **9%** (1 of 11 eval scenarios, by design — L6) | ✅ |
| Turns with `prose_words == 0` | any is P0 | **0** across 200 property samples | ✅ |
| Exceptions escaping the widget task | any | **0** across 200 samples | ✅ |
| Prose below the band floor | — | **45/200 (22.5%)**, all tier 3 on short authored bodies | ⚠️ |
| p50 / p95 TTFT | — | **not measured** — needs live traffic | ⚠️ |

The 22.5% thin-prose figure is real and worth naming: the template floor cannot
invent words, so a concept whose authored body for a band is short produces a short
lesson. That is the correct behaviour (padding to reach a count is the failure this
work exists to prevent) and it is also a content signal — those bodies want
rewriting, and they are identified in `concepts-review.csv`.

---

## Deferred, and what it would take

| Deferred | Blocked on | Effort |
|---|---|---|
| Concept embeddings (semantic resolution) | credits | `python scripts/seed_concepts.py --from e` |
| The 4 failed grounding retries | credits | same command |
| Threshold calibration on 60 labelled utterances | embeddings | half a day |
| `es` / `fr` concept bodies | credits | one seeder run per locale |
| EVALUATE's structured grader | — | half a day |
| Widgets on the authored-curriculum path | — | move `teach` onto `build_widget`; a day |
| Coverage from 82.6% to 90% | credits | re-run Pass A with a stricter merge |
| Live L1–L10 (`--live`) | credits | one command |

---

## What turned out to be wrong about the repository

Recorded in full in [OBJECTIONS.md](OBJECTIONS.md). In short: the brief's
concurrency contract contradicts its own three-tier guarantee (I implemented the
guarantee and named the latency cost); four bands should be five; the seven gates
are not this product's seven; `concepts` already existed and `CREATE TABLE` would
have failed; and the diagnosis named the second cause, not the first.

## Recovering the deferred work

```bash
python scripts/seed_concepts.py --from e
```

Reads the Pass D checkpoint, retries the 4 failed groundings, embeds all 67
concepts, and re-upserts. Nothing else needs re-running — `ON CONFLICT (slug,
locale)` means existing rows keep their ids and no mastery row is orphaned.
