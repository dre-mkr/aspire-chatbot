# ASPIRE AI — Design Review

**Date:** 2026-08-01 · **Surface:** `frontend/src` · **Mode:** Operate (app UI)
**Method:** Impeccable skill (global install, `~/.claude/skills/impeccable`), dual-agent critique, mechanical detector, and purpose-built browser probes.

**Headline:** 5 confirmed defects fixed, 3 of them WCAG failures, one of which made the microphone consent panel — the single highest-stakes screen in a product for children — effectively unreadable. Design health **25/40 → 27/40**. Source detector **exit 2 → exit 0**. Ground-truth contrast **0 elements below AA** at every breakpoint in both phases.

The score moved only +2 because this round was legibility and target-size repair. The three heuristics carrying the real structural debt were deferred to you on purpose — see [Needs your decision](#needs-your-decision). **Two P0s remain open there, and both are business-logic changes I was scoped out of.**

---

## 1. Route and state inventory

The app is a single route. "Per page" collapses to one page with many states, so the review is organised by state, not by URL.

| Route | Component | Notes |
|---|---|---|
| `/` | `AspireChat` | The only route. `__root.tsx` is the document shell. |

Everything else is a **phase** (`data-phase` on `.app`) or a state within it.

| # | State | Phase | Reviewed at |
|---|---|---|---|
| 01 | Landing / empty | `landing` | D · C · M |
| 02 | Composer with draft | `landing` | D · C · M |
| 03 | Thinking | `chat` | D · C · M |
| 04 | Answer settled (bubble, prose, bullets, follow-ups) | `chat` | D · C · M |
| 05 | Sources expanded | `chat` | D · C · M |
| 06 | Voice + language menu open | `chat` | D · C · M |
| 07 | Rail toggled (collapsed desktop / drawer mobile) | `chat` | D · C · M |
| 08 | Error + retry | `chat` | D · C · M |
| 09 | **Microphone consent panel** | `landing` | D · M — *added mid-review; see below* |
| 10 | Voice listening / transcribing | either | source + CSS |
| 11 | Voice note (denied / no-speech) | either | source + CSS |
| 12 | Game cards (TrueFalse, WordScramble) | `chat` | source + CSS |
| 13 | Empty history | both | D · C · M |
| 14 | Long-string / overflow stress | `chat` | measured |
| 15 | 200% / 400% zoom | both | measured |

State 09 was **not** in my original sweep, because the consent panel is only reachable by pressing the mic. That omission is exactly how a 1.83:1 privacy notice survived to production — a reviewable-states list built from "what renders on load" misses the states that matter most. It is in the harness now (`.impeccable/consent-shot.mjs`).

**Auth-gated variants:** none exist. There is no account (`PRODUCT.md`). The `persona` prop that would gate the games and the copy register is never set by any caller, so the shipping UI is the unknown-persona UI, and that is the one reviewed.

### Breakpoints actually supported

Read from `styles.css`, not assumed:

| Query | Effect | Reviewed |
|---|---|---|
| `min-width: 700px` | Answer action row spacing | yes |
| `max-width: 860px` | **Rail becomes a modal drawer** (mirrored in JS as `COMPACT`) | yes (780px) |
| `max-width: 620px` | Compact composer, starters, `.tool-btn` label clipped | yes (390px) |
| `max-height: 600px` | Hero collapses — *this is also the 200% zoom path* | yes |
| `prefers-reduced-motion` | Motion and typewriter off | source |
| `forced-colors` | *Did not exist. Added by this review.* | added |

Review viewports: **D** = 1280×800, **C** = 780×900, **M** = 390×844.

---

## 2. Baseline findings

### Source scan — `detect.mjs --json src/`

| Rule | Count | Location | Verdict |
|---|---|---|---|
| `side-tab` | 2 | `styles.css:2470, 2488` | **REAL** — fixed |
| `bounce-easing` | 2 | `styles.css:2352, 2405` | **Deliberate** — waived |
| `overused-font` | 1 | `__root.tsx:51` | **Deliberate** — waived |

**Exit code 2.** After fixes and waivers: **exit code 0**.

### URL scan — production build, 3 viewports

| Rule | 1280 | 780 | 390 | Verdict |
|---|---|---|---|---|
| `low-contrast` | 10 | 9 | 9 | **1 real** (`.hero__sub`), rest false positives |
| `ai-color-palette` | 5 | 5 | 5 | False positive — this is the brand |
| `layout-transition` | 4 | 4 | 4 | Confirmed as code fact, cost unmeasured |
| `clipped-overflow-container` | 1 | 1 | 1 | False positive — only 1×1px `sr-only` children |
| `body-text-viewport-edge` | 1 | 1 | 2 | **1 real** (`.hero__sub` at 390), rest FP |
| `tiny-text` | 1 | 1 | 1 | **REAL, and undercounted** — 3 actual, not 1 |

### Two things about the tooling you should know

**The detector exits 0 when a URL scan *fails*.** My first URL run reported "exit 0, clean" while stderr said `puppeteer is required`. A second reported exit 0 on a navigation timeout. **Exit code alone is not evidence for a URL scan** — check stderr and non-empty JSON. Every URL number above was taken with both confirmed.

**`networkidle0` never settles against a Vite dev server,** so URL scanning against `localhost:3000` times out permanently. This review runs against a **production build** on `:4173` via `.impeccable/preview-server.mjs`, which is better anyway: the dev server renders `<TanStackDevtools>` into the page, and it would have polluted every screenshot.

### Why the URL scan cannot reach exit 0 — and why that is correct

The residual ~20 findings are **structural false positives**, not unfixed defects. This app keeps real text in the DOM while it is not painted:

- on `landing`, the rail is `--rail-w: 0px` — zero width, `inert`, text present;
- on `chat`, the hero is `opacity: 0` and `inert` — text present.

The detector measures that text and reports the layer *behind* it as a background. That is the entire source of the `#ffffff on #ffffff` and `#482977 on #482977` pairs at ratio 1.0:1. The detector's arithmetic is correct; its element selection is not phase-aware.

**I did not suppress these.** Ignoring `low-contrast` project-wide to reach a green number would disable the rule that caught the one real defect. The honest state is: **source exit 0, URL findings triaged individually with evidence.** Ground truth comes from `.impeccable/contrast-truth.mjs`, which blanks every glyph, screenshots, reads the actual painted pixel under each text run, and skips subtrees under a zero-opacity / zero-size / `inert` ancestor.

---

## 3. Judged review

Two isolated sub-agents: **A** (design review, blind to detector output) and **B** (detector + browser evidence). Neither saw the other until synthesis. A third agent re-scored after the fixes.

### Design health — Nielsen's 10

| # | Heuristic | Before | After | What moved |
|---|---|---:|---:|---|
| 1 | Visibility of system status | 2 | **3** | Real focus ring; filled pressed state |
| 2 | Match system / real world | 3 | **4** | Counts derive from data; placeholder names the gesture the device has |
| 3 | User control and freedom | 1 | **1** | *Unchanged — destructive retry is logic* |
| 4 | Consistency and standards | 3 | **3** | ARIA honest; voice settings still mislabelled |
| 5 | Error prevention | 2 | **3** | Consent panel went from unreadable to 11.1:1 |
| 6 | Recognition over recall | 2 | **2** | *Unchanged* |
| 7 | Flexibility and efficiency | 3 | **3** | Starters keyboard-reachable in the new scroll row |
| 8 | Aesthetic and minimalist | 3 | **3** | Overlap 238×5px → 0; stripes gone |
| 9 | Error recovery | 3 | **2** | *Re-scored down: long answers clip unrecoverably* |
| 10 | Help and documentation | 1 | **3** | Consent readable; rail note at 12px |
| | **Total** | **25/40** | **27/40** | |

Heuristic 9 went **down** on re-scoring — the second pass found a defect the first missed (assistant answers clipping), which is what independent verification is for.

### Cognitive load — 4/8 failed, before and after

Failures: recognition-over-recall, result-visible-where-you-look, destructive-actions-guarded, no-dead-ends. The count is unchanged because all four failures are structural. Item 1 (purpose readable in 5s) got materially stronger.

### AI-slop verdict: **clear — not generated design**

Both assessments independently reached this, and it is worth recording *why*, because it constrained the whole review. The comments explain **rejected alternatives**, not what the next line does: why fonts are a `<link>` and not an `@import` (a three-hop serial critical path); why there is no `will-change` on `.atmosphere`; why `.app` has no `min-height` ("a phone in landscape could read but not ask"). The greys were re-derived from measured ratios because the design-system originals sat at 4.2/2.9/1.9:1. A wrong guess in a game is **amber, not red**, with the reason in the token comment.

Slop is uniform. This is uneven — world-class reduced-motion handling next to a broken consent panel. That unevenness is the signature of authored work, and it is why this review fixed defects rather than restyling anything.

### Design specificity: **authored for this product**

Load-bearing product-specific decisions: the phase-driven layout (one attribute flipping seven custom properties), the gradient with drift that *pauses* in chat, the amber-not-red token, the single motion exception on game tiles, the scoped reduced-motion block that keeps progress indicators pulsing so a reduced-motion reader can still tell working from hung.

The honest caveat, from Assessment A: **strip the gradient and the orb and you are looking at a generic assistant.** The brand lives almost entirely in the background layer, not in the interaction. See question 6 below.

---

## 4. What changed

Ranked P0 → P2. Every fix is CSS or markup. **No business logic, API contract, data model, or routing behaviour was touched.**

### P0 — broken / inaccessible

**1. The microphone consent panel was unreadable.** `.voice-consent` and `.voice-note` used `background: var(--wash-3)` — a 3% plum tint that only reads as a panel when something white is already behind it. Both appear in the `landing` phase, where `--panel-bg` is `transparent` and the parent is the raw brand gradient. Measured on the running build:

| Element | Before | After |
|---|---:|---:|
| The three privacy promises | **1.83:1** | **11.35:1** |
| "A grown-up can turn this off in voice options" | **1.30:1** | **5.38:1** |
| "Before I listen" | **2.47:1** | **16.12:1** |

This is the one screen where a child is told what happens to their voice, and the one line addressed to a guardian was the least legible string on the page. Fixed with an opaque surface matching `.composer`; the three `data-tone` variants now layer their tint *over* that base instead of replacing it. Evidence: `.impeccable/shots/consent-{before,after}--{desktop,mobile}.png`.

**2. The composer had no perceivable focus indicator.** `.composer textarea` sets `outline: none` and delegates to `.composer:focus-within`, which drew the ring in `--hairline` — plum at 10%, about **1.1:1**. The product's primary control was keyboard-invisible (WCAG 2.4.7 / 2.4.11). Now plum at 45% (ring **4.99:1**, border 9.33:1), plus a `forced-colors` outline because Windows High Contrast strips `box-shadow` exactly where it is needed most.

**3. `.hero__sub` failed AA on the most-seen text in the product.** White at 82% opacity, weight 300, over the lightest, most magenta band of the gradient: **3.01:1** at 1280, 3.34 at 780, 3.58 at 390 — against a 4.5:1 requirement. Raising the text alone could not fix it; pure white on that background tops out near 3.7:1. So the background came down: a soft radial vignette on `.hero::before`, plus solid white at weight 400. Now **5.68:1 / 6.44:1 / ~5.9:1**. Verified as a smooth luminance ramp with no seam at any breakpoint and no flash in the landing→chat transition.

**4. Assistant answers clipped off the right edge, unrecoverably.** `.answer p` and `.answer li` computed `overflow-wrap: normal` while `.thread` is `overflow-x: hidden` — so a long URL produced **1058px of content in a 736px column with no scrollbar**, 322px permanently unreadable. *This one is on me: my first pass fixed `.bubble` (what the child types) and missed the side that actually emits URLs. The re-critique caught it.* Now contained: 736 vs 736.

### P1 — contradicts DESIGN.md or hurts the primary task

**5. Sub-12px text.** DESIGN.md states a 12px body floor; three elements broke it — `.rail__group-title` ("Today") 11px, `.rail__note` ("Chats are saved on this device") 11.5px, `.tf__pill-tag` 11px. All raised to 12px. The detector reported 1; there were 3.

**6. `.bubble` clipped long strings.** `overflow-wrap: anywhere` — a child could not read back their own question if it contained a long token.

**7. Touch targets below 44px on a product for children.** The codebase already had an elegant solution — an invisible `::after` overlay carrying the pointer target to 44px without inflating the painted box — applied to seven controls and skipped on four. Extended to `.follow-up`, `.tool-btn` and `.voice-switch`; `.history-item` got a real 44px height instead, because history rows are stacked with no gap and an overlay would have neighbours stealing each other's taps. Verified: **0 controls under 44px effective hit area**, 0 overlapping hit boxes.

**8. Four starter chips collided with the disclaimer on mobile.** Measured 238×5px of overlap, still clickable — a child could tap a suggestion and the safety line at once. Now one horizontally scrollable row: overlap **0px**, ~140px returned to the hero and composer, all four chips reachable by scroll, touch and keyboard.

**9. `.disclaimer` at 4.21:1 on mobile in the chat phase**, sitting on the panel tint rather than white. `--quiet` → `--slate` (now **7.92:1**), plus `env(safe-area-inset-bottom)` because the text was flush to the viewport edge — under the home indicator on a phone.

**10. Errors were announced twice.** The failure paragraph carried `role="alert"` *and* its text was pushed into the transcript's `<output>` live region. Removed the role; the live region already owns this.

**11. `role="menu"` wrapped plain buttons.** An ARIA menu promises menuitem children and arrow-key navigation; these are a switch, two sets of toggle buttons and a link. Now `role="group"` with `aria-label`, and the trigger uses `aria-controls` rather than `aria-haspopup`.

**12. TrueFalse hardcoded "5 statements"** while rendering `Statement {position} of {total}` and `total` pips — a four-item round said "5 statements" directly above "STATEMENT 1 OF 4". Counts now derive from `state.prompt.total`; closing lines rephrased count-free.

**13. The composer told phone users to press a key they do not have.** "hold Space to talk" was the only hint that voice input exists, and it is addressed to a keyboard. Now touch-aware via `(hover: none)`: "tap the mic to talk". Verified under CDP media emulation.

### P2 — polish

**14. `.tool-btn` pressed state was colour-only** — and under 620px its label is clipped, so a 10% tint was the only thing distinguishing plain-words on from off. Now a filled brand gradient (white text at **5.05:1** against the gradient's worst point) plus a `forced-colors` border.

**15. `border-left: 4px` colour tabs removed** from `.game__wrong` and `.game__clue` (`side-tab`). The craft floor bans coloured side borders above 1px on callouts; the tone is carried by the fill and the icon.

**16. Opening Sources hid the answer's action row and follow-up chips.** My first attempt used `scrollIntoView({ block: "nearest" })`, which **is a no-op when the element is already in view** — the normal case. The re-critique measured it doing nothing (scrollTop 0 → 0, chips 72px below the fold) and it was right. Corrected to scroll the *end of the transcript* instead. Now scrollTop 0 → 67 (desktop) and 113 → 316 (mobile), with both chips in view and reachable.

**17. Regression I introduced and fixed:** the new scroll row let `scroll-snap-align: start` eat its own left padding, resting the first chip 1px from the viewport edge. `scroll-padding-left: 16px` → now 17px.

**18. Regression I introduced and fixed:** making the consent panel opaque meant it sliced the `h1` mid-glyph at 390px instead of letting it bleed through. The hero now dims to 0.28 behind it via `:has()`, so the overlap reads as focus moving rather than a broken clip. Progressive enhancement — a no-op where `:has()` is unsupported, and the panel is readable either way.

---

## 5. Verification

| Check | Before | After |
|---|---|---|
| `detect.mjs src/` | exit 2, 5 findings | **exit 0** |
| Ground-truth contrast, 3 viewports × 2 phases | 4 failures | **0 below AA (6/6 clean)** |
| Consent panel contrast | 1.83 / 1.30 / 2.47 | **11.35 / 5.38 / 16.12** |
| Effective hit areas < 44px | 4 controls | **0** |
| Overlapping hit boxes | — | **0** |
| Starter ↔ disclaimer overlap (390) | 238×5px | **0** |
| Assistant answer containment | 1058px in 736px | **736 in 736** |
| Follow-ups reachable, sources open | below fold | **2/2 in view + reachable** |
| Document horizontal scroll | none | **none** (scroll row did not leak) |
| Sub-12px painted text | 3 | **1** (waived label) |
| Typecheck / build | — | **clean** |

Screenshots: `.impeccable/shots/before/` and `after/`, 8 states × 3 breakpoints, plus the consent pair. Tooling retained under `.impeccable/`: `preview-server.mjs`, `contrast-truth.mjs`, `layout-probe.mjs`, `verify.mjs`, `verify-round2.mjs`, `shots.mjs`, `consent-{shot,measure}.mjs`.

**One tooling correction worth keeping:** my first `contrast-truth.mjs` sampled the element's *block box*, which made the "ASPIRE AI" chip read 1.98:1 by sampling the decorative orb the glyphs never touch. It now samples `Range.getClientRects()` — the actual ink. If you re-run it, that false failure will not come back.

---

## 6. Waivers

Documented in-file, travelling with the code. **No rule was deleted or globally suppressed.**

| Rule | Where | Reason |
|---|---|---|
| `overused-font` | `__root.tsx` | Instrument Serif is the display voice for exactly one element (`.hero__title`), paired with Sora for UI and JetBrains Mono for measurement — a considered three-face system, not a default body font. *Your decision this session.* Revisit if it appears outside the hero. |
| `bounce-easing` ×2 | `styles.css` `.tile--tray`, `.tile--answer` | The only overshoot in the product, on game letter tiles — the one place the interface is meant to feel physical to a child. Collapsed to its final frame under `prefers-reduced-motion`. Documented as a deliberate exception in DESIGN.md. |
| 11px micro-labels | 7 selectors | Tracked uppercase chrome (`.rail__section-label` "HISTORY", `.voice-menu__label`, `.voice-choice__code`, `.game__clue-label`, …). DESIGN.md's 12px floor is for body text; these are scanned, not read. **`.tf__label` ("STATEMENT 1 OF 5") is the weakest of these to leave** — it is a progress indicator in a children's game. Flagged, not fixed. |
| URL `low-contrast` / `ai-color-palette` / `clipped-overflow-container` | detector | Structural false positives from phase-hidden text and from the brand gradient itself. Triaged individually rather than suppressed, so the rule still fires on real regressions. |

---

## 7. Conflicts between Impeccable's defaults and DESIGN.md

Logged rather than silently resolved, as instructed.

1. **`ai-color-palette` — "purple/violet gradient" is an AI-slop signal.** DESIGN.md states the gradient *is* the product's signature and is derived from the brand mark. **DESIGN.md wins.** Not changed. Worth noting the detector is not simply wrong in general — a full-bleed purple→magenta gradient is genuinely the house style of AI product landing pages. Here it is brand-derived and earned.
2. **`bounce-easing` — "bounce feels dated and tacky."** DESIGN.md pre-declares this exception with a stated reason and a defined scope. **DESIGN.md wins.**
3. **`overused-font`.** The rule's own description lists Inter, Roboto, Fraunces, Geist, Plus Jakarta Sans and Space Grotesk — Instrument Serif is not among them, so this may be a rule bug or an undocumented list entry. Waived on your instruction either way.
4. **Craft floor vs. incumbent: coloured `border-left` on callouts.** No conflict — DESIGN.md is silent, the floor bans it, so it was **fixed**.

---

## Needs your decision

Everything below is either **business logic** (explicitly out of scope for this pass) or a **product/IA decision** that is not mine to make. Ordered by severity.

### P0 — destructive, and the largest single drag on the score

**1. "Try again" deletes the newest answer, whichever one you press.** `use-conversation.ts` reads `lastQuestion.current` and does `current.slice(0, -1)`, so pressing "Try again" under answer 1 of 3 destroys answer 3 and re-runs question 3. Silent, unconfirmed, irreversible. A child scrolling back to re-read the first answer and tapping the nearest button loses the newest one. This alone holds *User control and freedom* at 1/4.
*Also:* the label is wrong on a success. "Try again" reads as *you got it wrong* — it is the last thing a child sees under every correct answer. It means "regenerate". I did not relabel it, because relabelling without fixing the truncation would hide a destructive bug behind friendlier words. **Fix wants: pass the turn id, and rename to "Ask again".**

**2. A refresh strands the user with their history unreachable.** `phase` resets to `landing`; the rail is `inert` at zero width there; the mobile drawer trigger only renders when `compact && inChat`. The product promises "Chats are saved on this device" and then, on the screen you land on, offers no route to them — on a phone, none at all until you send a new message. The data is already in `localStorage`.

### P1

**3. `persona` is never selected, so half the written product is unreachable.** `AspireChat` accepts the prop; nothing passes it. `scale` is permanently `"orion"`, and the entire `stella` register — a gentler voice written deliberately for a younger child — is dead code. Either wire a picker (the code comment says the games gate, the voice and the card scale all follow with no further change) or delete the second register. The half-state costs you both ways.

**4. All four starter prompts are enrolment questions.** "What is the ASPIRE Programme?", "Who is eligible to join?", "How do I apply?", "Does it cost anything?" — while the hero asks *"What do you want to learn about **money** today?"* and the stated primary users are young people **who have already joined**. The empty state's only guidance is written for a prospective applicant. This is the highest-value change available and it is a content decision, so it is yours. I did not touch the copy.

**5. A second question mid-flight orphans the first.** `send()` bumps `turnToken`, so the in-flight reply is discarded on arrival and the first user bubble sits in the transcript forever with no answer and no error.

**6. No way to delete or rename a stored conversation.** The rail advertises that chats are saved on this device; `history.ts` exposes only load and save. On a shared family tablet, a child's money questions persist for whoever picks it up next. For a product this careful about deleting voice audio, this is inconsistent with its own values.

### P2

**7. Voice settings live behind a chip labelled "ASPIRE AI".** Read-aloud, 4 speeds, 3 languages and the privacy explainer are all behind the product's own name. `PRODUCT.md` names "reading ability is not a barrier" as a success criterion — so the feature carrying that promise is the least discoverable thing on screen. **This is an IA change, so I stopped.** My recommendation: a speaker glyph plus "Voice", separate from the brand mark. Also worth disabling Speed and Language while the master switch is off.

**8. The mic stays rendered-but-disabled when voice is unavailable,** explained only by `title` — which does not fire on touch. A child taps a visible button and nothing happens. This also contradicts `PRODUCT.md`'s own stated constraint that unavailable controls disappear rather than sitting there disabled. Which of the two is correct is your call.

**9. At 200% and 400% zoom the landing page has no heading and cannot reflow.** `@media (max-height: 600px)` sets `--hero-opacity: 0` / `--hero-max: 0`, hiding the only `h1`; the `sr-only` substitute renders only in the chat phase. At 400% (320×512) the starters are clipped away and `.app { height: 100dvh; overflow: hidden }` prevents scrolling — content lost, not reflowed (WCAG 1.4.10, 2.4.6). **The fix is structural** — it means letting the landing phase scroll — and that is a deliberate layout decision I did not want to overturn unasked.

**10. `.tf__label` at 11px** ("STATEMENT 1 OF 5") — a progress indicator in a children's game, currently inside the tracked-label waiver. Say the word and I will raise it.

### Housekeeping

**11. I did not commit anything, deliberately.** Your working tree already contained ~1,123 lines of uncommitted work in `styles.css` alone, plus the whole games feature, backend changes and `deploy/` — all pre-existing when I started, on `main`, with one commit in history. Committing "per page with rule ids" as you asked would have swept your in-progress work into my commits and misattributed it. Tell me how you want it split and I will branch and commit properly. My changes touch: `src/styles.css`, `src/components/chat/{Transcript,TopBar,Composer,TrueFalse}.tsx`, `src/routes/__root.tsx`, plus new `PRODUCT.md`, `DESIGN.md`, `DESIGN-REVIEW.md`, `.impeccable/`.

**12. Puppeteer was added** to `frontend/package.json` as a devDependency (your call this session) and also installed into the skill directory, because the detector resolves `puppeteer` relative to its own location and could not see the project's copy. Dev-only, never bundled. Removable when you are done reviewing; the skill-dir copy makes URL scanning work for your other projects too.

**13. `.impeccable/` is untracked and currently unignored** — add it to `.gitignore` if you would rather not carry the review tooling and screenshots.

---

## Questions worth sitting with

Sharpest from the critique, none of them answerable by a detector:

1. **The gradient is the brand — so why does it disappear the moment the product is used?** In `chat` the frame covers all but 16px, the atmosphere pauses, and the surface becomes 97% white. The signature exists only on the screen where nothing has happened yet. Should it survive into the conversation?
2. **What if the composer *were* the whole product on landing, and the hero were the placeholder?** The hero spends `min(380px, 44vh)` asking "What do you want to learn about money today?" while the composer's placeholder says "Ask me anything" and the composer itself is ~120px of empty space. Two elements are doing one job.
3. **Should sources be a disclosure at all?** A collapsed "2 sources" chip is a thing a designer opens and a child ignores. What if the count were an inline marker on the sentence it supports, so evidence attaches to the claim?
4. **Why does the microphone live in the composer instead of being the composer?** If reading ability must not be a barrier, the current answer is a 40px icon beside a text field. For a child who reads poorly, what does this screen look like if voice is the default input?
