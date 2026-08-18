# Product improvements and UX update

2026-08-18 · branch `main` · baseline `8d88345`

Nine requested items. Each row below names the seam that was changed and the
measurement behind it — no status here says DONE without something re-runnable.

## What the documents asked for, measured against the tree

The Fix Sheet and Supplement G describe nine transitions. Six were already
repaired before this work; three were not, and were verified rather than assumed:

| Fix | State found | Evidence |
|---|---|---|
| 1 · teaching questions to the tutor | **not applied** | `qa_agent` still ended `"...how the programme works"`; `git log -S` shows the phrase never touched since it was written |
| 2 · real ASPIRE contact detail | already done | `reports/client-checklist-status.md`, judging 11 |
| 3 · anonymous visitor → adult persona | already done | finding 1; `e2e/lib/identities.mjs` identity A expects stella/5-8 |
| 4 · keyword gate | **partly applied** | question-word guard on 3 of 7 matchers, no length guard anywhere |
| 5 · corrected reply stored | already done | `test_what_is_stored_is_what_was_sent` |
| 6 · stickiness | **not applied**, and not reproduced | 0 matches repo-wide; `reports/findings.md` measured the 0.75 threshold never firing against a real switch over four probes |
| 7 · `_coerce` fallback | **not applied**, currently inert | every access-matrix row already leads with a qa_* variant, so `allowed[0]` is always the same answer a preference order would give |
| 8 · `servicing_agent` unbuilt | already true | `UNBUILT` strips it from every menu |
| 9 · language switch | already done | judging 9 (ES), judging 10 (FR) |

Fix 1 and the missing half of Fix 4 were applied. Fixes 6 and 7 were left alone
and are recorded under *Not done* below.

## The nine items

### 1 · Help / How to use

`frontend/src/components/chat/HelpPanel.tsx` (new). A `role="dialog"` panel with
`aria-modal`, Escape to close, a Tab trap and focus return — the recipe
`VoiceSettings` already used. Ten sections cover what ASPIRE AI is, who it is
for, the five personas and how to switch, voice, Explain it simply, games,
eligibility, applying, capability limits, and safety.

Reached from a **How to use** entry in the rail, placed outside `rail__body` so a
long history cannot scroll it away. Desktop: a centred panel. Under 860px: a
bottom sheet, measured pinned to the viewport (top 65 → bottom 812 at 375×812,
`documentElement.scrollWidth == 375`, no horizontal overflow).

**One gap this exposed and closed:** `.rail-open` on the landing page was gated on
`hasHistory`, so a first-time visitor — with nothing in their history and the
most reason to want help — was the only reader who could not open the rail at
all. The gate is gone; the empty history has always had its own written state.

### 2 · Personas that change the answer

Three things were true and one was not. The persona cards existed and reached the
prompt; the band was stated to the model; the caps were enforced. But
`QA_AGENT_ROLE` — the strongest length instruction in the QA prompt — was
persona-blind and said *"Be thorough… use every extract… structure a longer
answer"* to every reader, so it argued with Stella's "about eight words" from a
stronger position and won.

- `agents/qa/nodes.py` — the role card is now `qa_agent_role(persona)`. The
  GROUNDING half is byte-identical for everyone (it is load-bearing for
  `ground_check`); only the DEPTH half varies. An unknown persona gets the
  fullest one.
- `prompting/personas/*.md` — each card gained an explicit **LENGTH** target and
  a **TEACHING** rule, the two dimensions the request names that the cards did
  not state.
- `prompting/personas/everyone.md` (new) — see below.

**Measured.** Same question, five personas, through the real HTTP surface:

| persona | band | words |
|---|---|---|
| stella | 5-8 | 44 |
| orion | 13-15 | 65 |
| aurora | adult | 56 |
| nova | adult | 104 |
| everyone | 13-15 | 56 |

Aurora and Nova share `band=adult`, so every band-keyed control — caps, vocabulary
ladder, link stripping, lesson contract — is identical for them. 56 against 104 is
the persona layer alone. Stella's answer ends by asking her a question back, which
is the TEACHING rule added to her card.

### The `everyone` persona

The picker's "Everyone" sent `persona=null`, which resolved to Stella at the 5-8
band: the general-purpose option answered everyone like a five-year-old.

`everyone` is now a real persona in `domain.Persona`, with its own card, its own
game bank and its own voice delivery. Two decisions worth recording:

- **It is a voice, not a privilege.** `access.allowed_agents` resolves it to the
  safe default for the band the token already carries, so every result is a set
  that band already had. It can never widen what a reader reaches, which is also
  what makes `_narrowing` admit it from any account. `TestEveryoneNeverWidens`
  walks every band and status.
- **Band `13-15`, not `adult`.** The reader behind it may be a child, so it stays
  inside a minor band's caps, vocabulary ladder and link strip while still
  reading as plain adult prose. Choosing `adult` would have handed an unknown
  reader the ungated row and reversed commits `ee6f144` / `fe82b0d`.

`voice/registry.py` gained an understudy so a deployment provisioned with twelve
voice ids still boots: `everyone` borrows Orion's id unless `VOICE_EVERYONE` is
set. An explicit id always wins.

### 3 · Games

**The headline defect was not the content.** The engine's persona filter existed
and was correct; nothing called it. `ChatScreen.tsx` started every game with no
persona, so `_servable(entries, None)` matched everything and a five-year-old on
Stella was served the Orion set — compound interest, 5% returns, "no more than
25% in any one sector" — while `truefalse-stella-01`, written for her, was
unreachable.

Fixing that one argument arms a second gate, so both were done together:
`PLAYING_PERSONAS` admits stella/orion/everyone, and the *card* gate now checks
persona as well as band. Previously the card opened for a guardian (band `adult`
clears `BAND_MIN`) and `POST /api/games/start` then refused the same request, so
the card rendered and sat dead.

`engine.start` now gathers servable entries across every set a persona can be
served rather than stopping at the first file — otherwise a second set for the
same persona is unreachable by construction and "add more questions" has nowhere
to go. A caller with no persona keeps the old first-set-only behaviour.

Pools, before → after:

| | Stella | Orion | Everyone | Aurora/Nova |
|---|---|---|---|---|
| Word scramble | 4 (shared) | 4 (shared) | 0 | 0 |
| | **10** | **11** | **8** | none, by design |
| True/False | 5 | 5 | 0 | 0 |
| | **11** | **11** | **8** | none, by design |

True/False draws 5 per round, so a bigger pool is variety rather than length.
Every new item carries its own `explanation`, `takeaway` and laid-out
`paragraphs`, authored natively for its persona — the frontend already rendered
all three.

The ECCB handout is untouched and still leads: a Stella round opens on `NOEYM`,
the printed first word, in the printed order. `WordScramble.tsx` no longer
hardcodes a closing paragraph naming SAVE/INVEST/INTEREST/MONEY — it reads
`GameSet.closing`, which the true/false card already used.

Verified through the API: aurora and nova receive `403 not_available_for_persona`
and no longer get a card that leads to it.

### 4 · Explain it simply

**It was a no-op.** The button rendered a pressed state, the setting persisted in
the URL and survived navigation, and every layer carried the value down to
`streamAspire` — whose destructure dropped it. Nothing crossed the wire.
`SIMPLE_MODE_INSTRUCTIONS` had been written for it and was imported by nothing.
`backend/README.md` still documents it on a `POST /chat` endpoint that no longer
exists.

Joined end to end: `stream.ts` sends it on the chat path only (the widget and
game-result endpoints post typed bodies that must not gain a key) → `hydrate`
lifts it into `AspireState` per turn → the QA agent appends it through the
`extra_instruction` hook `build_messages` already had.

It shapes the answer **at generation**, from the same retrieved extracts, so no
fact can be invented and `ground_check` still runs. A QA-specific clause protects
the two things a simplifying pass is most likely to drop: the `[ASP-xxx]` markers
and the figures.

The answer cache is keyed on it — otherwise the first thing the control does is
serve back the complex answer it was turned on to avoid. The flag is present in
the key only when set, so ordinary answers keep the keys they already have and
nothing on the shelf was invalidated.

A **Simpler** button now sits under every answer, beside Ask again, for the
answer already on screen. It re-asks that question with the flag on through the
existing `regenerate` path, so the facts and sources are the ones already checked
— not a fresh question.

**Measured on the wire:** on → `{"message":"How does the money grow?","simple_mode":true}`;
off → `{"message":"What documents do I need?"}`, byte-identical to before.

### 5 · Casual input

The model never had trouble with a typo. The deterministic gates in front of it
did: `_small_talk_reply` matches an anchored closed list, so "hello" was answered
and "helo", "hiiiiii", "yo" and "hey there lol" fell through into retrieval,
where a greeting matches nothing and returns a decline.

`app/casual.py` (new) normalises **for matching only** — the model always sees
what the reader actually wrote. Three rules: runs of three or more identical
letters collapse (no English, Spanish or French word carries a triple letter), a
closed table maps everyday variants to canonical words, and laughter is dropped
from the edges of a message but never from the middle.

The opposite property is tested just as hard: "yo what is aspire" must **not** be
swallowed as a greeting. It folds to "hi what is aspire", which the anchored list
misses, and goes to the router.

`GLOBAL` gained a **HOW PEOPLE WRITE TO YOU** section: read the intent, never
correct anyone's spelling, and match their warmth rather than their vocabulary —
no slang back, and no compensating stiffness.

**Fix 4's remaining half.** A word-count ceiling now guards the card matchers, so
*"Can my daughter play a game about who is eligible?"* (ten words) reaches the
model instead of the eligibility card. The sheet also proposed banning
question words; applied literally that suppresses *"can we play a game?"* and
*"Do I qualify?"*, which are exactly what those two cards are for — so the guard
is length only, and the existing per-matcher question-word tests stay where they
were tuned.

### 6 & 7 · Opening and first-run onboarding

`FirstRun.tsx` (new). A ~1.4s branded opening, then *"Who are you using ASPIRE AI
as?"* with the five personas and a line saying the choice changes how it writes.
Skippable by any key or click, `Escape` leaves without choosing, and
`prefers-reduced-motion` skips straight to the question.

Shown once, keyed `aspire.intro.v1`, read in a mount effect rather than a
`useState` initialiser — the rule every stored preference here follows, because
`window` does not exist during SSR. The consequence is that a first-time reader
sees it one frame late rather than immediately, which is the right trade against
every returning reader seeing a flash of it. The app renders behind it throughout;
nothing waits on it.

Verified: choosing Orion sets `?persona=orion`, updates the picker, stores the
flag and dismisses; a reload shows nothing.

### 8 · UI and responsiveness

Done as part of the above rather than as a separate pass: the persona menu now
lists five real options instead of four plus a null, Help is reachable from the
rail at every width, the new surfaces use the existing tokens (`--plum`,
`--wash-*`, `--hairline`, `--control-line`, `var(--ease)`), onboarding targets are
64px minimum for the youngest readers, both new overlays honour
`prefers-reduced-motion`, and both were measured for horizontal overflow at
375px. No new colours, fonts or radii were introduced.

## Preserved

RAG and retrieval untouched — no change to embeddings, the vector store,
`qa_relevance_floor` or the reranker. Knowledge base unchanged. Tutor, curriculum,
widgets, voice, eligibility, registration, escalation, conversation history and
staff/admin untouched. `GLOBAL`'s `LOAD_BEARING` clauses survive verbatim. The
prompt-cache breakpoint holds: everything added to `stable_prefix` is a pure
function of persona, band and agent role.

## Not done, deliberately

- **Fix 6 (stickiness) and Fix 7 (`_coerce`).** Out of the nine requested items,
  and both argue against measured evidence: the 0.75 threshold was observed never
  to fire against a real switch, and every access row already leads with a qa_*
  variant so a preference order is currently a no-op. Recorded rather than
  shipped.
- **`AgeBandProvider` is still mounted only in `/admin`.** Turning it on in the
  chat changes the type size of ~60 widget and card call sites at once, and its
  unknown-band fallback is the 5-8 config. It is a real gap against "text sizing
  for different age bands" and wants its own change with its own verification.
- **The persona picker's SSR hydration mismatch** (`reports/findings.md` finding
  7) is pre-existing and untouched: `useSession` is client-only, so the trigger's
  label differs between passes. Fixing it properly needs the session on the
  server.

## Verification run

| gate | result |
|---|---|
| `pytest -m "not slow"` | **3814 passed**, 2 failed, 1 skipped, 1 xfailed (10m05s) |
| `python -m evals.harness` | **PASSED** — `band_violations` 0, `ungrounded_answers_served` 0, `pii_leaks_into_summary` 0, safety 100%, widget validation 100% |
| `tsc --noEmit` | clean |
| `biome lint` (changed files) | clean |
| `vite build` | clean |
| persona probe, 5 personas via HTTP | 44 / 65 / 56 / 104 / 56 words — see §2 |
| game probe, 5 personas via HTTP | stella 10, orion 11, everyone 8 scramble items; aurora and nova `403 not_available_for_persona` |
| simple-mode wire capture | `simple_mode: true` present when on, key absent when off |

The two failures are
`tests/register/test_document_loop.py::TestANonSensitiveSlotCanActuallyBeSaved`
— both **pass in isolation** (3 passed), both resolve SQL expressions against
Postgres, and no file changed here touches registration. Consistent with the
single shared dev database this repo runs against under a concurrent run.

The baseline for comparison was 3482 tests collecting before this work; the count
rose because the access matrix is walked exhaustively over `PERSONAS`, which
gained a member, and because 90-odd tests were added.

## Still to verify

- **The live routing-accuracy suite** (`tests/graph/test_classify.py`, slow-marked)
  needs a provider key and is configured for `openai:gpt-4o`. Fix 1 changes six
  router descriptions and could not be measured against it here. The gate has
  ~2.9 points of margin (87.9% against 0.85, four cases structurally unpassable),
  so **run it before shipping Fix 1**, watching `r11` and `r18` in
  `evals/routing.jsonl`.
- **The judging suites**, which are outside `--suite all` — in particular
  `judging-compare.mjs`, which fails if two personas are more than 80% alike.
  The persona work should move that number, and it is the natural regression
  guard for it.
- **`VOICE_EVERYONE`** is unset, so the new persona currently speaks in Orion's
  voice. Give it an ElevenLabs id when one is available.
- **Spanish and French game seeds** remain unauthored, deliberately: the loader
  rejects a translated scramble because the letters stop matching the word.
  `everyone`, `stella` and `orion` banks are English only.
