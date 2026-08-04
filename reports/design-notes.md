# Design notes — observations only, none implemented

Everything here is **taste-based or structural, meets no permitted trigger, and
has not been changed**. It exists so opinions have somewhere to go that is not a
diff. Read once, ignore most of it.

Anything that *does* meet a trigger (a–g) is in `reports/findings.md` instead,
with its trigger letter, awaiting approval.

---

## Consistency

**Two icon-button sizes for the same job.** "Expand sidebar" renders at 40×40 and
"Collapse sidebar" at 36×36 — the same control in its two states, four pixels
apart. Nothing breaks; it is just two numbers where there should be one token.

**Three sizes of secondary action.** The rail row menu is 30×30, the composer's
adjacent controls are 40×40, and the auth links are 18px tall. There is no
obvious rule deciding which a given secondary action gets. *(The sizes themselves
are in the ledger as P10-003 — this note is about the inconsistency, not the
minimum.)*

**Two ways to say "not signed in".** `AccountControl` renders a single button
whose accessible name is the concatenation `"Not signed inSign in to keep your
chats"` — two strings in one control, which reads oddly to a screen reader and
suggests the label and the caption were meant to be separate elements.

---

## Tokens and magic numbers

`styles.css` defines a token layer (`--starters-row`, `--composer-min`, and the
brand custom properties) and then bypasses it in places — `min(168px, 22vh)` and
`0.7fr` are inline decisions that read like tokens but are not named as such.
Several `translateY(-3px)`, `0 8px 18px` shadow values and one-off `rgb(53 29 90 /
0.2)` sit outside the palette variables. None is wrong; collectively they make the
system harder to change in one place.

`#33165c` appears once, as the `theme-color` meta. It is not in the stated brand
palette (purple `#482977`, magenta `#C22F99`, grey `#6D6E71`). It is a darker
purple — probably deliberate for the mobile browser chrome, but it is a fourth
brand colour with no home in the system.

`#6D6E71` — the stated brand grey — **does not appear in the built CSS at all**.
Either the palette documents a colour the product does not use, or the grey in use
comes from somewhere else. Worth reconciling the brand doc with reality.

---

## States that have no visual representation

Cross-referencing P4-001, which found that no component reads any TanStack Query
status flag. The consequence in design terms:

- **Loading vs empty are the same screen.** The rail renders `rail__empty` whether
  it is still fetching or genuinely has nothing. On a slow connection a returning
  user is told they have no conversations, then they appear.
- **Error has no representation at all** in the rail. This one is *argued* in the
  code (`queries.ts:83-86`) and I am not calling it wrong — but it means a failed
  load is indistinguishable from success, with no retry affordance.
- **Background refetch is invisible.** No indication that the list is being
  refreshed, which is fine, but it means stale data and current data look
  identical.
- **Offline has no state.** Nothing distinguishes "the network is gone" from "the
  service failed".

The design question, which is yours and not mine: does the rail deserve a skeleton
for first load, given the deliberate decision that its *failure* should stay quiet?

---

## Duplication

`Rail.tsx` and `AuthSurface.tsx` both render the wordmark from
`/brand/aspire-wordmark.png`, with different dimensions (190×48 vs unspecified —
the unspecified one is in the ledger as P6-005). Two call sites, two treatments,
one asset.

The empty state, the error turn and the "stopped" turn are three variants of the
same shape (icon + short sentence + optional action). They are implemented
separately. Consolidating them would be a refactor with no user-visible change,
which is exactly the kind of thing not to do during an audit.

---

## Copy

The interface writes at an adult reading level throughout — "Explain it simply",
"Stop generating", "Regenerate title", "Ask again". For a product whose youngest
stated audience is five, none of this is readable by the youngest users. This is
the same decision as P3-005 (persona is not wired), and it should be settled once
rather than per-string.

"Ask again" and "Try again" both appear, meaning different things (re-ask the
question vs retry a failed request). Two similar phrases for two different
actions is the kind of thing that reads fine to whoever wrote it and confuses
everyone else.

---

## Things I liked and would not change

Worth recording so a future pass does not "improve" them:

- The **thinking orb** and voice indicators keep animating under
  `prefers-reduced-motion` while everything ornamental stops. That is the correct
  distinction between decoration and state, and it is rare to see it made.
- Follow-up chips and sources are **laid out from the first tick** of the reveal
  and merely become visible, rather than mounting at completion. P5 measured the
  result: **0.0000 CLS during the entire reveal.** The comment explaining why
  (`use-conversation.ts:82-92`) is accurate.
- The conversation title **crossfades** when the generated one replaces the
  truncated question, and the rail deliberately does **not** reorder on retitle
  (`queries.ts:247-252`) so a row never moves out from under the cursor.
- Game and eligibility cards render **at their position in the transcript**, not
  pinned to the end, so the conversation continues past them naturally.

None of these is accidental, and all four are the kind of detail that gets
flattened by a well-meaning redesign.
