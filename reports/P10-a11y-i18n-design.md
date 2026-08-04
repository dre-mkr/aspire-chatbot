# P10 — Accessibility, internationalization, design integrity

Diagnosis only. **No UI was changed.** Every candidate that meets a permitted
trigger is in the ledger with its trigger letter, awaiting approval. Everything
taste-based is in `reports/design-notes.md`, unimplemented.

Method: axe-core 4.10.2 injected into the production build in real Chrome, across
five screens and three conversation states, at 390×844. Plus keyboard traversal,
touch-target measurement, live-region enumeration, and a runtime language switch.

---

## 1. Automated scan — **0 axe violations**

| Screen | State | axe violations (wcag2a/2aa/21a/21aa) |
|---|---|---|
| Landing | empty | **0** |
| Conversation | 3 turns | **0** |
| Conversation | 40 turns | **0** |
| Sign in | — | **0** |
| Sign up | — | **0** |

That includes axe's `color-contrast` rule, which is a stronger answer to the
contrast question than palette arithmetic: **every foreground/background pair
actually rendered passes AA.**

**The brief's predicted failure is not one.** Computed directly:

| Pair | Ratio | Body (4.5) | Large (3.0) |
|---|---|---|---|
| **magenta `#C22F99` on white** | **5.05:1** | **PASS** | PASS |
| grey `#6D6E71` on white | 5.10:1 | PASS | PASS |
| purple `#482977` on white | 11.30:1 | PASS | PASS |
| black on magenta | 4.16:1 | FAIL | PASS |
| magenta on purple | 2.24:1 | FAIL | FAIL |
| grey on purple | 2.22:1 | FAIL | FAIL |
| grey on magenta | 1.01:1 | FAIL | FAIL |

The bottom four would be serious — but **none of them is used**. `#6D6E71` does
not appear in the built CSS at all (only `#482977` ×34, `#c22f99` ×13, `#33165c`
×1), and axe confirms no rendered pair fails. Recorded so nobody "fixes" a
non-problem, and so anyone introducing grey-on-magenta later knows it is 1.01:1.

---

## 2. Screen reader — **the core interaction is silent (P10-001, S1)**

```
live regions found:  landing 0 · conversation 0 · long conversation 0 · signin 0 · signup 0
```

**There is no `aria-live`, `role="status"`, `role="log"` or `role="alert"`
anywhere in the product.**

The consequence is specific and serious. The answer is revealed by a typewriter
over several seconds (`use-conversation.ts`, 4 words per 40ms tick). A sighted
user watches it appear. **A screen reader user is told nothing at all** — no
announcement that a reply started, none that it finished, and no way to know the
answer is there short of manually re-reading the page.

This is WCAG **4.1.3 Status Messages (Level AA)** and it is the product's primary
interaction. axe cannot catch it because it is an *absence*, which is exactly why
the brief asks for a manual pass.

The same gap covers every other state: "thinking", errors, "You stopped this
answer", and the rate-limit and failure messages from P4-001 are all
unannounced.

**I did not test with an actual screen reader** (NVDA/JAWS/VoiceOver). I am
reporting the structural absence, which is unambiguous, rather than claiming a
manual SR pass I did not run.

---

## 3. Keyboard — no trap, but the composer is last

Tab traversal over 45 presses on a conversation screen:

```
 1 Voice and language settings     6 Hi? (user message)
 2 Explain it simply               7 Copy answer
 3 <body>  ← dead stop             8 Ask again
 4 Sign in                         9 More? (follow-up)
 5 Open conversations             10 textarea (composer)   → wraps
```

**No keyboard trap.** The cycle wraps cleanly at 9 reachable stops. 21 focusable
elements exist in the DOM, 10 of them inside the collapsed sidebar's `[inert]`
region (`Rail.tsx:131`) — correctly skipped.

**Focus is visible at every single stop** — 0 of 45 stops lacked an outline or
box-shadow. That is better than most production apps.

**P10-004 (S2): the composer is last in the tab order.** For a chat product the
input is the primary control, and reaching it requires tabbing past every message
action first. Measured: 25 focusable elements at 3 turns, **99 at 40 turns** — so
the number of Tab presses to reach the input **grows linearly with conversation
length**. This is the keyboard analogue of P5-001.

**P10-007 (S3):** one dead Tab stop per cycle (position 3), where focus lands on
`<body>` while passing the inert sidebar. Harmless, mildly confusing.

---

## 4. Touch targets (P10-003, S2)

Interactive elements below 44×44 CSS px, at 390px wide:

| Screen | count |
|---|---|
| Conversation (3 turns) | **18** |
| Conversation (40 turns) | **92** |
| Landing | 3 |
| Sign in / Sign up | 2 each |

Worst offenders:

| Size | Control |
|---|---|
| **30×30** | "Actions for {conversation}" — the per-row rail menu |
| 36×36 | "Collapse sidebar", "Open conversations" |
| 40×40 | "Expand sidebar", "Show password" |
| **131×18** | "Create an account" link |
| **49×18** | "Sign in" link |

**A precision note the brief does not make:** ≥44×44 is WCAG 2.1 **Level AAA**
(2.5.5), not AA. WCAG 2.2 adds 2.5.8 at Level **AA** with a **24×24** minimum. So
against strict WCAG 2.1 AA these are not violations; against WCAG 2.2 AA the
**18px-tall links fail**, and against the brief's own 44px bar most of them do.

I am reporting against the brief's bar, flagging which are AA failures under 2.2,
and leaving the standard choice to you — it is a programme decision, and for an
audience that includes 5-year-olds on phones I would argue for the 44px bar
regardless of what the standard requires.

---

## 5. Reduced motion — **correctly handled**

`styles.css:4443` and `:5101`. The block:

- turns off ambient/ornamental animation (`.atmosphere`, `.orb--hero`,
  `.orb--thinking`, `.voice-stars`, `.game__stars`, `.auth__orb`)
- collapses entry animations to `animation-duration: 1ms`
- applies a **global `*, *::before, *::after { transition-duration: 1ms !important }`**,
  which covers the compositor→dock transition (the P5-002 CLS source) without
  needing to name it
- **deliberately keeps** `.thinking__dots`, `.voice-spinner` and `.voice-rec__dot`
  animating with `!important`

That last decision is the right one and worth crediting: those indicators *report
state*, and freezing them would remove the only feedback that something is
happening. Someone thought about the difference between decoration and
information.

The typewriter is also handled in JS — `prefersReducedMotion()`
(`use-conversation.ts:121,558`) skips the reveal entirely and settles the answer
at once.

---

## 6. Internationalization — **the headline finding**

### P10-002 (S1): there is no i18n system

Tested at runtime by switching the stored language preference and reloading:

```
es: html lang="en"   chrome strings changed: 0/14
fr: html lang="en"   chrome strings changed: 0/14
```

**Not one string of the interface changes.** Every button, label, `aria-label`,
placeholder, empty state and error message is a hardcoded English literal:

> "Not signed in" · "Sign in to keep your chats" · "Explain it simply" ·
> "Stop generating" · "Send message" · "Expand sidebar" · "Collapse sidebar" ·
> "New chat" · "Open conversations" · "Read answers aloud" · "Date of birth" ·
> "Choose a school" · "Copy answer" · "Ask again"

There is no i18n library, no message catalogue, no translation keys. Language
currently affects exactly three things: the language the **model replies in**, the
**voice locale**, and the **game/eligibility conversation titles** (three inline
`Record<string,string>` objects in `use-conversation.ts`).

So a Spanish-speaking child gets a Spanish *answer* inside an entirely English
*interface*. For a Government of St Kitts and Nevis deployment stating EN/ES/FR
support, that is a launch blocker of the political rather than technical kind.

**Backend errors compound it.** Every user-facing message from the API is English
only — `"The assistant is temporarily unavailable. Please try again."`,
`"A valid session is required."`, `"Too many voice requests."` — and the client's
own `describeFailure` strings likewise.

### The screenshot exercise is moot — and I want to be explicit about that

The brief asks for screenshots of every screen in all three languages at 375px to
find overflow, clipping and wrap failures under longer French strings.

**Those screenshots would be byte-identical**, because the chrome is never
translated. Producing three copies of the same image and reporting "no overflow
found" would be a false pass. The layout risk the brief is chasing is real but
**cannot be assessed until translations exist** — French runs ~20% longer, and
several controls measured here are already tight (the 74×40 "Sign in", the 30×30
menu). Re-run this exercise as the first check *after* i18n lands.

### P10-006 (S3): no locale-aware formatting

No `Intl.NumberFormat`, no `Intl.DateTimeFormat`, no currency formatting anywhere
in the client. The single formatting call is `savedAt.toLocaleString()`
(`export.ts:47`) with **no locale argument**, so it follows the browser's locale
rather than the app's selected language.

**XCD is never formatted.** Currency appears only as literal text inside KB
answers (`EC$1,000`), which is consistent but means the amount is never presented
in the reader's locale conventions.

### P10-005 (S2): `lang` never updates

`__root.tsx:69` hardcodes `<html lang="en">`, confirmed unchanged at runtime after
switching to ES and FR. WCAG **3.1.1 Language of Page (A)** and **3.1.2 Language
of Parts (AA)**. A screen reader will pronounce Spanish and French answers with
English phonetics — which, combined with §2, means the assistive-technology
experience in ES/FR is doubly broken.

---

## 7. Age appropriateness (Stella)

I could not evaluate this as intended, and the reason is itself a finding.

The four personas exist in the backend — prompts, voices, games config — but
**persona is never set in the client** (P3-005): `AspireChat` is called once with
no props, so `persona` is permanently `null`. There is no Stella mode to test.

What I can say: the interface assumes fluent reading. Controls are labelled with
text ("Explain it simply", "Stop generating", "Ask again"), the empty state is a
sentence, and the only iconography is small and unlabelled to a non-reader. A
7-year-old could tap the starter chips and read an answer, but could not discover
"Explain it simply", change voice settings, or recover from an error without an
adult.

**That is a product observation, not a defect** — Phase 1 may not target
independent 7-year-old use. It needs a decision, and it is the same decision as
P3-005.

---

## 8. Summary

**7 findings: 0 × S0, 2 × S1, 3 × S2, 2 × S3.**

**Worst — P10-002 (S1):** there is no internationalization. 0/14 interface strings
change with language, in a trilingual government product.

**Second — P10-001 (S1):** zero live regions, so the answer a child waits for is
never announced to a screen reader. The product's core interaction is inaccessible
to assistive technology.

The automated picture is genuinely good and I want to be fair about it: **0 axe
violations across five screens and three states**, every rendered colour pair
passing contrast, visible focus at every one of 45 tab stops, no keyboard trap,
inert regions correctly skipped, and reduced-motion handling that distinguishes
decoration from state indicators. Somebody has clearly cared about this.

What is missing is the part automation cannot see: announcements, translations,
and target sizes for small hands.
