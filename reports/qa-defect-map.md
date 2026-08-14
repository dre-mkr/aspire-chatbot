# The QA findings, located in the code

2026-08-13 · branch `fix/judging-readiness` · baseline tag `pre-judging-fixes` (`2c8e529`)

The 13 Aug QA run scored the deployed app 62% (15.5/25), band *Demo-Ready*, capped at
**NOT READY FOR LIVE USERS** by a safety override. This file locates every finding in
the source, so the fixes that follow are aimed rather than guessed.

Read the corrections section first. **Eleven of the brief's premises are wrong**, and
four of them would have sent a day's work in the wrong direction.

---

## Corrections to the brief

| The brief says | Measured |
|---|---|
| Contact details exist nowhere; the fix is blocked on a human input | They exist twice over — KB rows `ASP-208/209/210/211/212`, and in code at `app/eligibility/content.py:8-15` |
| The launch year may be missing from the corpus | `ASP-006`, September 2024. The live failure is retrieval, not content |
| Two demo accounts are needed | `frontend/e2e/lib/identities.mjs` already seeds six |
| ES/FR voice ids are needed | All twelve persona×language pairs already resolve, and startup **fails** if one does not (`app/voice/registry.py:71-97`) |
| Build an API-level suite at `scripts/regression/` | `frontend/e2e` already is that harness, and judges each turn against three sources rather than one |
| The intent gate matches bare substrings | It folds accents and matches `\b`-anchored regex behind two veto sets. The real defect is six *informational* phrasings filed as personal intent |
| Complaint detection is too narrow | It already fires on the brief's own example, and already takes precedence over everything except safeguarding |
| Five post-hoc safety gates | **Six** — the quick-reply contract is missing from the list |
| Nine call sites bypass the layered prompt | **Eleven**, and the worst of them is the safety re-prompt itself |
| Choose between buffering and a token holdback | **Nothing token-streams.** Every prose call is `ainvoke`; the answer already crosses the wire as one frame |
| The stored transcript keeps the uncorrected text | Worse — **two transcripts diverge.** Postgres keeps the uncorrected text, the checkpoint keeps the corrected one |

---

## (a) The keyword intent gate

`cards` runs **before** `classify`, so a claimed card answers with no model call at all.

- Wiring — `app/graph/main_graph.py:296-337`; `_after_cards` at `:250-261`.
- Gate body and precedence — `app/graph/nodes/cards.py:169-205`: widget/game short-circuit `:171-174`, eligibility `:179`, game `:183`, asked-for-a-person `:189`, signup `:194`, registration help `:199`.
- Predicates — `app/graph/nodes/intents.py`. `_fold()` at `:12-17` lowercases, strips accents and normalises apostrophes; every predicate is `\b`-anchored. `_LOOKUP` (`:21-34`) vetoes `wants_eligibility`; `_ASKING_ABOUT` (`:129-132`) vetoes `wants_registration` and `wants_account`.
- A second, earlier gate skips the answer cache for card-shaped messages — `app/api/stream.py:135`, `_wants_card` at `:296-300`.

**The defect is not the matching style.** `tests/agents/test_intent_cards.py` names the intended split itself: `test_personal_eligibility_questions_open_the_card` against `test_lookups_stay_prose` ("A question about ONE rule gets a cited answer, not a form"). Six patterns sit on the wrong side of it:

| Line | Pattern | Why it is a lookup |
|---|---|---|
| `intents.py:45` | `who (is\|are) eligible` | asks the rule, not "am I" |
| `:46` | `who can (join\|apply\|…)` | same |
| `:48` | `how (can\|do) (i\|we) (apply\|…)` | asks the process |
| `:49` | `how (to\|do you) (apply\|…)` | same |
| `:50` | `what do (i\|we) need to (apply\|…)` | same |
| `:51` | `what (documents\|papers\|paperwork) do (i\|we) need` | **this is QA scenario 2** |

Spanish `:58,59` and French `:67,68` have the same shape.

The corpus already disagrees with the gate: `evals/golden.yaml` `en-02` ("Who is eligible to join ASPIRE?" → `ASP-026`) and `en-03` ("How do I apply for ASPIRE?" → `ASP-045`) expect both to be **answered**.

Measured against the live predicates:

```
message                                          elig   reg    complaint
What documents do I need to register my child?   True   False  False
Who is eligible to join ASPIRE?                  True   False  False
How do I apply for ASPIRE?                       True   True   False
wat de age range for aspire?                     False  False  False   <- _LOOKUP vetoes, correct
I want to register my child now                  False  True   False   <- correct
```

**Also found, not in the brief:** `cards.py:171-174` short-circuits on `widget_interaction` and `game_result` but **not on an open registration**. A slot answer containing "unacceptable" (`intents.py:203`) hijacks an in-flight registration into an escalation.

## (b) Starter chips

Four, hardcoded frontend-only at `frontend/src/lib/aspire/knowledge.ts:252-258`, rendered at `components/landing/LandingScreen.tsx:382-395`, sent verbatim as the first message by `startConversation` (`:125-161`).

Chips 2 and 3 are worded to hit `intents.py:45` and `:48` exactly, so both open the eligibility form with **zero prose**. Chips 1 and 4 answer normally.

## (c) Anonymous account and age band

- The account row is created on page load: `use-session.ts:36` → `session.ts:124-159` → `POST /api/auth/anonymous` → `app/sessions.py:115-157`, which **always inserts a new `User`** (`:140-146`), never looks one up by device id.
- `band_for` — `app/graph/account.py:26-42`. **A missing DOB reads as `adult`** unless `is_minor` is set.
- Two endpoints disagree for the same visitor: `sessions.py:73-78` forces `stella`/`5-8` (with a comment naming the hazard), while `account.py:146 _ANONYMOUS_DEFAULT = "aurora"` and `anonymous_claims` (`:149-158`) accept **any** of the four personas with no refusal. `/v2/session` therefore mints `aurora`/`adult`.
- The frontend ignores the stella one — `use-answer-settings.ts:22-23` reads `session.persona` only when `accountType === "registered"`.
- Every DB-failure fallback in the same file already returns `stella`/`5-8` (`:171-173`, `:212-214`, `:218-220`), so the anonymous default contradicts the file's own convention.

## (d) Persona resolution

Three distinct mechanisms behind one reported symptom:

1. **The silent revert is a frontend cache.** `lib/stream/session.ts:17` holds `new Map<string, GraphSession>()`; `:50-51` returns the held session. `forget(threadId)` is called from one place only (`lib/aspire/stream.ts:175`, on `unauthenticated`). Changing the persona picker mid-conversation changes the URL and the UI but **not the token the turns run under**.
2. **The refusal is correct behaviour.** An adult account requesting `orion` → `access.py:103-109` returns `[]` → `_narrowing` False → `account.py:114 refused = True`. Notice at `use-answer-settings.ts:73-85`.
3. **"The assistant could not be reached"** — `lib/aspire/stream.ts:66-74`, thrown when `POST /v2/session` returns non-ok (`lib/stream/session.ts:84-86`). Root cause unidentified; the leading hypothesis is an un-retried transient (see (j)).

Fallback persona is `aurora` — `app/prompting/personas/__init__.py:15`, and `account.py:80` for an unknown band. An unknown persona therefore loses all child-safety wording.

## (e) Sessions and rate limits

`app/api/stream.py:603-604` takes `session_id` and `device_id` **from the request body, unvalidated**, and mints them into the signed token (`app/graph/identity.py:46-77`). `sid` becomes the LangGraph `thread_id`, the conversation id *and* the rate-limit key.

The graph forbids client-supplied identity on the *turn* body (`identity.py:116-124`, enforced at `hydrate.py:53-61`) but accepts it on the *mint*.

Three problems, worst first:

1. **Thread ownership fails open.** `app/turn.py:127-128` returns `True` when the conversation row is missing **or has a null owner**, and `:122-125` returns `True` on a DB error. Anonymous conversations have no owner.
2. Rotating `session_id` resets the chat rate bucket (`app/limits.py:82-104`, key precedence `u:` → `s:` → `ip:`).
3. `/v2/session` has no rate limit and no cap on tokens minted per caller.

`limits.py:22-47` is in-process — per worker, not shared.

## (f) Voice endpoints

`app/voice/router.py` — `/config` `:46`, `/transcribe` `:83`, `/speak` `:174`, `/speak-stream` `:246`, `/realtime-token` `:339`. **None reads an Authorization header or takes a principal**, and the client sends none (`frontend/src/lib/aspire/voice.ts:100-106,140-150`).

Spend controls are a sliding window keyed on `_session_key` (`:33-38`) — `thread:{client-supplied thread_id}`, falling back to the raw `request.client.host` — plus the audio cache. `/speak-stream` returns a cache hit at `:282-288` **before touching the limiter**.

The same unauthenticated shape exists on `app/eligibility/router.py:37,147-203`.

## (g) Complaints and escalation

- `is_complaint` `intents.py:210-213` (patterns `:195-207`, en/es/fr) is checked **before** `wants_human` `:216-221` in the same call — `cards.py:208-222`.
- `safety_flags["asked_for_human"]` routes straight to `escalate_agent`, bypassing `classify` — `main_graph.py:253-255`.
- Safeguarding outranks everything: `main_graph.py:243-247` fires before `resolve_context`/`cards`.
- Tickets — `app/agents/escalation/graph.py:167` (`ASP-` + 8 hex), triage `:40-56`, `_persist` `:274-297`. A child's message and directive carry no reference and no SLA (`:85-98`, `:224-232`).

**There is no name-collection flow in escalation.** The only "what is your full name?" is the registration slot `app/agents/register/schema.py:297-313`. So QA scenario 5 reaching a name prompt means the message was routed to `register_agent` — i.e. the complaint regex did *not* fire on that phrasing. Measured, `"Nobody is answering the phone…"` **does** fire. Reproduce the exact wording before widening anything.

## (h) Distress and safeguarding

`app/graph/nodes/safety_in.py:93-107` (`_SAFEGUARDING`) and `:109-123` (`_DISTRESS`), dispatched by `distress_level` `:126-132`, invoked at `:233-242`.

**English only**, and — unlike `intents.py` — this path does **not** fold accents; the raw message is matched at `:200-201`. Measured:

```
I want to kill myself   -> safeguarding
quiero morirme          -> None
je veux mourir          -> None
```

A Spanish or French disclosure passes straight through to the router. This is the most serious unfixed finding in this file.

## (i) The summariser

`SUMMARY_AFTER_MESSAGES = 12` (`main_graph.py:133-134`) against `RECENT_TURNS = 6` (`context/session_context.py:14-15`, also a schema cap at `:68`). The summary covers `messages[:-12]`; the verbatim window is `messages[-6:]`. **Indices −12…−7 are in neither** — six messages, three exchanges. `build_messages` (`prompting/builder.py:58-81`) emits nothing else that could carry them.

Two things the brief does not mention:

- **The in-graph summariser is dead in production.** `make_persist(summarise)` (`main_graph.py:140-179`) is never given a `summarise=` argument by `api/stream.py:153-159`. The live path is `turn.py:314-363`, run after the SSE `done` frame.
- **It re-sends the whole older history every turn.** `turn.py:338-351` passes the previous summary *and* all of `messages[:-12]`, framed as "New turns to fold in" (`agent.py:114-134`). Cost grows linearly with thread length.

`MEMORY_WINDOW_ENABLED` is unset in `backend/.env` so the code default `True` applies (`config.py:190`) — but `.env.example:173` ships `false`.

## (j) Observability

- **The chat path never binds `app.timing`.** `api/stream.py` does not import it, so all 20 stage constants are no-ops on a chat turn; `record_stage`/`annotate` return early (`timing.py:310-331`). Only the two voice endpoints call `timed_turn` (`voice/router.py:177,249`).
- The QA path also **bypasses `TimedRetriever`** — `agents/qa/graph.py:83` reaches through to `.inner` and mutates `k` in place — so retrieval timing stays blank even once timing is bound.
- Four provider-usage fields are declared and never written: `timing.py:158-166`. `agent.py:50-52` already sets `stream_usage=True` and nothing reads the result.
- `/debug/timings` is 404 unless `TIMINGS_ENDPOINT_ENABLED` (`main.py:202-207`, `timing.py:438-445`). It is set in `backend/.env`.
- **No tracing exists** — no LangSmith, OTel or Sentry configuration anywhere. Those packages are transitive dependencies only.
- `timing.py:59,136,203` reference a `TurnBuffer` that no longer exists in the tree.
- The only chat latency figure emitted today is `elapsed_ms` on the `done` frame (`stream.py:249,336`).

The richest existing per-turn line is the learning agent's — `agents/learn/tutor.py:1002-1024`. The routing line is `graph/nodes/classify.py:332-341`. **The e2e harness asserts on these shapes** (`frontend/e2e/lib/server.mjs:139-156`), so they change together or not at all.

## (k) The streamed answer and the six safety gates

**Nothing token-streams.** Every prose call is `ainvoke` — `agents/qa/graph.py:147`, `agents/learn/graph.py:695` — and there is no `astream` or `streaming=True` in the tree. LangGraph emits per-token only from `on_llm_new_token`, which never fires; it falls through to `on_llm_end` and emits the whole `AIMessage` in one `_emit`. `stream_interceptor._token()` (`:263-277`) sends it as a **single frame**.

The gates are post-hoc purely because of the graph edge `agent → safety_out` (`main_graph.py:333-334`). `safety_out`'s own model calls are suppressed from the wire (`stream_interceptor.py:31`) and its corrected message is deduped by id reuse (`safety_out.py:403`).

| # | Gate | Where | Re-prompts? |
|---|---|---|---|
| 1 | Age word caps | `safety_out.py:284-300`; tables `:25-54`, selector `:57-65` | yes, `:288` |
| 2 | Banned vocabulary | `:302-325`; `app/safety/vocab.py:27-91` | yes, `:307`, then excises |
| 3 | Outbound PII | `:327-337`; `app/safety/pii.py:123,149,169` | no — deterministic |
| 4 | Link stripping under 16 | `:339-344`; `_NO_LINK_PERSONAS` `:68` | no |
| 5 | **Quick-reply contract** | `:346-367` | yes, `:358` |
| 6 | Language | `:369-390`; `detect_locale` `:224-239` | yes, `:380` |

Worst case is **five model calls in one turn**, four of them wasted because the reader already has the first answer.

**Two transcripts diverge.** `stream.py:258` sets `record.reply = interceptor.prose` — the *uncorrected* text — and that reaches Postgres (`turn.py:171-213`) and the response cache (`turn.py:277-300`). The checkpoint gets the corrected version (`safety_out.py:400-404`). The model reads back a version of its own answer the reader never saw.

**A hazard for the contact-details work:** `pii.py:29-34 _PHONE` matches `+1 (869) 667-5566` exactly and `_EMAIL` matches `aspire@gov.kn`. Adding contacts to a decline template without an allowlist renders "[a phone number]" — and only once the gates actually affect delivered text, which is why it has never been seen.

## (l) Prompts

Layers — `app/prompting/builder.py:21-27 stable_prefix` = `GLOBAL` (`global_rules.py:7-57`) + persona card (`personas/*.md`) + agent role card. Only three call sites use it: `qa/nodes.py:341-346`, `learn/teach.py:186-191`, `learn/render.py:574-579` — and **each silently falls back to a non-layered prompt on exception** (`qa/nodes.py:347-360`, `teach.py:192-195`, `render.py:580-585`).

- **Neither the age band nor the locale is ever written into a system message.** `SessionContext` carries both (`context/session_context.py:61-62`); `stable_prefix` uses only `persona`, and `_turn_context` (`builder.py:30-45`) emits only the date and display name. The band reaches the model only in the *re-prompt*, after it has already got it wrong (`safety_out.py:124-125`).
- **The depth conflict, in one composed message** for a 13-18 reader: `qa/nodes.py:269-272` ("Be thorough… then the conditions, exceptions, amounts, deadlines and next steps") against `personas/orion.md:8-9` ("Answer the question that was asked, then stop") and `global_rules.py:43` ("Lead with the answer, then the detail") — while `QA_WORD_CAPS` (`safety_out.py:48-54`) caps 13-15 at 280 words.
- **Eleven bypass sites**, worst first: `api/stream.py:409-431 _reprompt` (what all four re-prompting gates call — no global rules, no persona, no injection defence), `classify.py:379-394`, `qa/graph.py:160-164`, `learn/graph.py:724-755` (×3), `learn/graph.py:758-774`, `widgets/planner.py:260-261`, `register/nodes/doc_check.py:268-282` (builds its own `init_chat_model`), `agent.py:76-106`, `agent.py:109-150`.
- **Injection defence** — `global_rules.py:30-32`, pinned load-bearing at `:65-66`; deterministic detector at `safety_in.py:18-87`.

### Dead prompt code, and the tests that certify it

The v1 pipeline was deleted (tombstone at `app/main.py:291`); its prompt layer survives, reachable only from tests.

| Dead | Definition | Referenced by |
|---|---|---|
| `ASPIRE_SYSTEM_PROMPT` (88 lines) | `app/prompts.py:21-108` | `tests/test_prompts.py`, `tests/test_kb_injection.py:154` |
| `SIMPLE_MODE_INSTRUCTIONS` | `prompts.py:111-118` | **nothing, not even a test** |
| `GAMES_INSTRUCTIONS` (43 lines) | `prompts.py:121-163` | `tests/games/test_tools.py:147-154` |
| `memory.build_prompt` and friends | `app/memory.py:61-140` | `tests/test_memory.py`, `tests/test_kb_injection.py:80,122` |
| `rag.context_from` / `format_context` | `app/rag.py:245-256` | `tests/test_kb_injection.py:123` |

`tests/games/test_tools.py:146` asserts the games rules forbid inventing content — **those rules are currently told to no model at all**. Live coverage of the real layer is `tests/context/test_prompt_layers.py`.

## Language

- **No layered prompt contains a reply-language rule.** Checked all 57 lines of `global_rules.py`, all four persona cards, `QA_AGENT_ROLE`, both learn roles and `builder.py`. Language is stated only by `safety_out.py:245-251`, post-hoc, and only when the reply has ≥8 words (`:227-228`) — short replies are never checked.
- Most of the codebase localises correctly via `dict[str, str]` keyed en/es/fr read with `.get(locale, TABLE["en"])` — `guard.py`, `safety_in.py`, `escalation/decline.py:10-55`, `register/*`, `cards.py`, `qa/nodes.py:696-727`. The gaps are `learn/render.py:321-402` (the whole deterministic lesson floor and the decline, with **no locale parameter in scope**), `learn/tutor.py:907-923` and `learn/teach.py:336` (chips), `cards.py:384,395` (`_GAME_LABELS`), `turn.py:58-75` (history lines written into the transcript), and every `interceptor.error(...)` in `stream.py`.
- **The KB is English-only** — 0 of 706 rows contain ES/FR diacritics. ES/FR answers are the model translating English rows, and QA follow-up chips (`qa/nodes.py:596-629`) are lifted verbatim from corpus rows, so they cannot be localised by retrieval.

## Voice

- **STT force-decodes to the interface language.** `voice/router.py:135` builds the hint from the UI language and `voice/client.py:110` passes it as `language_code=` — a hard setting, not a bias.
- **The detected language is carried all the way to the client and dropped.** `client.py:133-134` → `router.py:166-171` → `voice.ts:21-26` all carry `language_code` and `language_probability`; `use-voice.ts:218` reads only `result.text`.
- **Every TTS request uses the staff voice.** `frontend/src/lib/aspire/voice.ts:5` hardcodes `DEFAULT_PERSONA = "nova"`, and `speakStream` (`:121-126`) takes no persona parameter. A six-year-old reading a Stella lesson hears Nova.
- The backend is already fully persona- and language-aware and entirely unused: `registry.py:105-114 resolve_profile`, `:46-68` builds all 4×3 combinations, `:37-43` resolves a language override then falls back to the persona base, `:71-97 validate_registry` **raises at startup** if any of the twelve is unmapped, and `:25-30` holds per-persona delivery settings.

## Retrieval and latency

- **The BM25 index is rebuilt per question from a full table read.** `agents/qa/nodes.py:134-144` calls `bm25_rank` (`:90-104`) each turn; its corpus comes from `agents/qa/graph.py:115-141`, an unbounded `SELECT` of every document row with a Python-side filter. No cache, no TTL. `app/main.py:82-144 lifespan` never touches it.
- **No retries anywhere.** `tenacity` is transitive and never imported in `backend/app`. Generate, classify, rewrite, embed, rerank, pgvector, mail — all one-shot. The only backoff in the repo is the Valkey client (`cache.py:101-109`, one retry, ≤200 ms). Voice has a circuit breaker (`client.py:32-75`) but no retry.
- Per-chunk context given to the model is `[kb_id] content` only (`builder.py:48-55`); title, question, category, audience, `source_url`, `as_of` and score are all discarded.
- The semantic cache is finished, tested and uncalled — `cache.py:289-437`, with the author's note at `:308`: *"LAYER 2 IS OFF AND HAS NO CALLER."*

## Frontend

- **The composer drops keystrokes before hydration.** `components/chat/Composer.tsx:180-191` — the textarea has no `disabled` prop and no ready gate; the only gated control is the send button (`:282`), and `busy` is a *streaming* flag, hardcoded `false` on the landing page (`LandingScreen.tsx:370`). Both routes are full-document SSR. The e2e harness already works around it with a four-attempt retry loop and says so — `frontend/e2e/lib/turn.mjs:74-98`.
- **The passwordless sign-in link is discarded.** `mail.py:60` sends `/signin?token=…`; `routes/signin.tsx:26-29 validateSearch` returns only `{ next }` and nothing reads `token`.
- **The verification link redeems against the wrong purpose.** `routes/verify.tsx:23-35` calls `redeemSignInLink` → `_redeem(…, "signin_link")` (`accounts.py:443`), but a verify token has `purpose="verify"`, so the lookup misses and the reader is told "That link has been used" — which is untrue. `POST /api/auth/verify` (`accounts.py:454-469`) exists and **has no client**. Reset works correctly and is the shape to copy.

## The knowledge base

706 rows, `backend/data/knowledge_base.csv`, ingested into Postgres (`app/ingest.py`), auto-seeded on boot (`main.py:70`), boot fails hard if empty.

Both "UNVERIFIED" checklist items close with no code change:

- **Scraped site data is present** — `source_url` spans `aspire.gov.kn`, `sknis.gov.kn`, `technology.gov.kn`; `as_of` mostly 2026-07-30 and 2026-08-04.
- **The launch date is present** — `ASP-006`: *established by the Government of Saint Kitts and Nevis in September 2024, announced by Prime Minister Dr. Terrance Drew at the Independence 41 National Youth Rally on 13 September 2024*. Corroborated by `ASP-007`, `ASP-048`, `ASP-148`. Its `keywords` column carries `launch|established|start date|when|2024`, so the term is in both indexes.

Contact details, sourced `as_of` 2026-07-30: `ASP-208` email `aspire@gov.kn`; `ASP-209` phones `+1 (869) 667-5566` and `+1 (869) 762-1947`; `ASP-210` both; `ASP-211` `aspire.gov.kn`; `ASP-212` in-person support; `ASP-299`/`ASP-300` the Cable Office, Mon–Fri 09:00–15:00; `ASP-303` hotline 465-2588. The same values are already hardcoded at `app/eligibility/content.py:8-15`.

**These must be confirmed with the client before the 20th.** They are cited corpus rows rather than invention, but a stale number on a government service is a client-visible error.

---

## Two notes on the environment

`backend/.env.example` has drifted from the code defaults on roughly fourteen settings, including `CHAT_RATE_WINDOW_SECONDS` (60 documented, 600 actual), `CLASSIFIER_STICKINESS_THRESHOLD` (0.6 / 0.75), `QA_RELEVANCE_FLOOR` (0.15 / 0.55) and `MEMORY_WINDOW_ENABLED` (false / true). Anyone provisioning from it gets a differently tuned system.

`ruff` is still absent from `backend/.venv`, but it does not need to be there: CI runs `uvx ruff check app/ --select F,E9` (`deploy.yml:85`) and `uv` is installed locally, so the gate runs as-is. It passes clean at `pre-judging-fixes`.
