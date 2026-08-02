# ASPIRE AI — Design System

> Documented from the shipping code (`src/styles.css`, `src/components/`) on
> 2026-08-01. This records what the product **is**, and is the authority for the
> design review. Where a generic design opinion conflicts with this file, this
> file wins and the conflict is logged.

## Voice

Warm, plain-spoken, and addressed to a young person. Never clinical. Copy states
what will happen ("Your voice becomes text in a few seconds, then the audio is
deleted"), never what a policy permits. Errors say what went wrong and what to
do next, never a status code.

## Colour

The palette is defined once in `@theme` and aliased into short names in `:root`.
**Every tint against a brand colour derives from a `--wash-*` token** so a
palette change cannot leave a stray `rgba()` behind.

### Brand

| Token | Value | Role |
|---|---|---|
| `--plum` | `#482977` | Structural brand colour |
| `--plum-light` | `#6b42a1` | Gradient partner, earned states |
| `--plum-deep` | `#351d5a` | Gradient top, shadow tint |
| `--magenta` | `#c22f99` | Selected and recording states only |
| `--magenta-light` | `#d94db3` | Gradient partner |

### Text — contrast is measured, not eyeballed

| Token | Value | On white | Use |
|---|---|---|---|
| `--ink` | `#1a1a2e` | — | Headings |
| `--prose` | `#2d3748` | — | Body |
| `--slate` | `#554d63` | 7.99:1 | Quiet body |
| `--quiet` | `#6a6177` | 5.85:1 | Secondary text |
| `--faint` | `#857d92` | 3.93:1 | **Icons and rules only — never text** |

The greys are tinted from the brand purple rather than left neutral: the
original design-system greys sat at 4.2 / 2.9 / 1.9:1, two of them below AA.

### Status

| Token | Value | Note |
|---|---|---|
| `--success` | `#16a34a` | |
| `--danger` | `#b3261e` | 5.9:1 — a failure has to be readable |
| `--warn` | `#d97706` | Line colour only (3.1:1) |
| `--warn-ink` | `#b45309` | Text colour (5.1:1) |

A wrong guess in a game uses **amber, not red**: it says "not yet" where red
would say "you broke something."

### Gradient angles

Two brand gradients, and the angle is not free choice:

| Pair | Angle | Where |
|---|---|---|
| `--plum → --plum-light` | `90deg` | Wide controls: the send button, `.game__btn--go` |
| `--plum → --plum-light` | `135deg` | Compact and square: user bubble, earned tiles, done steps, word pills |
| `--plum → --magenta` | `135deg` | Identity only: the orb, the rail mark, the voice control |

The split is real and was previously undocumented, so each new widget picked one
at random. **A wide control takes `90deg`; anything roughly square takes
`135deg`.** The plum-to-magenta pair is the product's mark and is never a button.

### The page gradient

`.app` is a single 7-stop vertical gradient, `#33165c → #ffffff`, with four
blurred, slowly drifting `.atmosphere` blobs over it. **This is the product's
signature.** It is deliberately purple, is derived from the brand mark, and its
animation pauses in the chat phase.

Consequence: **white text over the 36–67% band of the gradient is the one place
contrast has to be checked by measurement**, because the background there is
both light and moving.

## Type

- **Sora** (300–700) — everything UI and prose. `--font-sans`.
- **Instrument Serif** (400) — `.hero__title` only. `--font-display`.
- **JetBrains Mono** (400) — the recorder clock and language codes, where the
  glyphs are a measurement. `--font-mono`.

Loaded as a real `<link>` in `__root.tsx`, never `@import` in CSS, so the
browser finds the fonts in its first HTML scan instead of three hops deep.

The size scale is fine-grained (0.6875–1.0625rem) plus a fluid hero at
`clamp(1.875rem, 3.4vw, 3.25rem)`. **Body text floor is 12px** — see the review
for the two places that broke it.

## Space and shape

**The Two Radii Rule.** Anything pill-shaped is `999px`. Everything else that a
finger touches is `14px`. Those two cover 42 of the ~60 radii in the stylesheet;
the rest are structural one-offs (the `26px` composer, the `24px` card, the
asymmetric `24px 24px 8px 24px` user bubble) and each has to earn its value.

This replaces a looser "`14px` / `16px` for cards" that let controls inside a
single card run 12, 14 and 16px at once. **Inside a card there is one control
radius and it is `14px`** — the exit button, the action buttons, the True/False
choices and the eligibility options are all the same shape.

- `--reading-width: 780px` caps prose. A widget card measures 736px inside it.
- Rail is `272px` open, `78px` shut. (78, not 76: at 76 the rail's own border
  and padding left the content box at 39px and clipped the 40px mark by a pixel.)
- **There is no spacing scale.** 51 distinct `padding` values are in use and only
  three are tokens (`--head-pad`, `--body-pad`, `--nest-pad`). This is a known
  gap, recorded rather than papered over: do not cite a scale that does not exist.

### Icons

One set, `src/components/icons.tsx`, `viewBox="0 0 24 24"`, stroked not filled.
Sizes vary by role (13 / 14 / 15 / 16 / 18). **Stroke is always `1.9`** — it is
what makes the set read as one hand. It previously ran 1.8 through 2.2, which at
a glance reads as blur rather than as variety.

### Disabled

One token, `--disabled: 0.45`, on every disabled control in a card. Before this
there were four opacities (0.38 / 0.45 / 0.5 / 0.55) and two controls that
carried `disabled` with no disabled styling at all.

## Motion

| Token | Value | Use |
|---|---|---|
| `--ease` | `cubic-bezier(0.4, 0, 0.2, 1)` | Everything |
| `--swift` | `150ms` | Hover, press |
| `--settle` | `300ms` | State change |
| `--morph` | `560ms` | Phase change |

The one deliberate exception is `cubic-bezier(0.34, 1.56, 0.64, 1)` on game
letter tiles — an overshoot, used only where a child is being told a tile
landed. Everything respects `prefers-reduced-motion`, including the typewriter.

## The two phases

The whole layout is driven by `data-phase` on `.app`, which flips custom
properties that every consumer transitions on its own schedule.

| Property | `landing` | `chat` |
|---|---|---|
| `--rail-w` | `0px` | `272px` (`78px` collapsed) |
| `--hero-opacity` | `1` | `0` |
| `--hero-max` | `min(380px, 44vh)` | `0px` |
| `--starters-row` | `0.7fr` | `0fr` |
| `--panel-bg` | `transparent` | `rgb(255 255 255 / 0.97)` |
| `--composer-min` | `min(168px, 22vh)` | `112px` |
| `--input-h` | `min(96px, 12vh)` | `46px` |

`--frame-inset` and `--frame-radius` used to be in this table. **They no longer
exist in the code** — the frame stopped insetting itself in the chat phase, and
the `28px` this file cited as "the chat frame" radius went with it. Removed here
rather than left as a token the next agent would try to honour.

**This is why a naive scan of the rendered page is unreliable here**: on the
landing screen the rail is zero-width but present, and in the chat phase the
hero is `opacity: 0` but present. Both keep real text in the DOM. Any contrast
or layout check must skip subtrees under a zero-opacity, zero-size, or `inert`
ancestor, or it will report the layer behind them as a defect.

## The card

There is **one** in-thread card. The word scramble, the True/False round and the
eligibility pre-check are the same object with different jobs, not three widgets
that happen to sit together. Anything new that renders inside the transcript
uses these, and adds only what its own job needs:

| Primitive | Class | What it is |
|---|---|---|
| Container | `.game` | `24px` radius, white, 1px `--wash-14`, one shadow, `pop-in` |
| Header | `.game__head` | badge, title, optional subtitle, progress, exit |
| Exit | `.game__leave` | hard right in every card; the label may differ, the control may not |
| Progress | `.game__steps` / `.game__step` | numbered circles, `done` / `now` / `next`, plum |
| Eyebrow | `.game__eyebrow` | 11px uppercase, `0.07em`, `--quiet`, with `.game__rule` |
| Marker | `.game__chip` | mono, tabular, pill |
| Buttons | `.game__btn` + `--clue` / `--quiet` / `--ghost` / `--go` | `14px`, `--btn-h` |

**The One Progress Rule.** "n of m" is drawn one way in this product: numbered
circles. The eligibility card used to draw flat bar segments instead, because
its numbered steps shared a header line with a subtitle that ellipsised. The
card dropped that subtitle; the second progress language went with it.

**The No Borrowed Namespace Rule.** A card never reaches into another card's
classes. `.tf__*` belongs to True/False and `.elig__*` to the eligibility flow;
anything two cards need is `.game__*`. The eligibility card previously used
`.tf__rule` and `.tf__chip`, so restyling the quiz silently restyled it.

### The card lives inside `.answer`

Prose rules in the transcript are scoped with the child combinator (`.answer > p`,
not `.answer p`) **and this is load-bearing.** `.answer p` is specificity (0,1,1)
and every card's paragraph rules are single-class at (0,1,0), so the descendant
form silently overrode 22 paragraph classes across all three cards at once and
flattened every one of them to 15.5px. Do not relax that combinator.

## Accessibility commitments already made

These are load-bearing. Do not regress them.

- Anything folded away is `inert`, so focus never lands on an invisible control.
- The drawer is modal: the workspace goes `inert`, focus moves in, Escape
  closes, and the trigger gets focus back.
- Discrete events are announced through an `<output>` live region — never the
  stream, which would read every four-word tick aloud.
- The hero `h1` goes inert with the hero, so a `sr-only` `h1` supplies the page
  heading in the chat phase.
- Model-authored links get `rel="noopener noreferrer"`.

## Breakpoints actually supported

| Query | What changes |
|---|---|
| `min-width: 700px` | Answer action row spacing |
| `max-width: 860px` | **Rail stops being a column and becomes a modal drawer** (mirrored in JS as `COMPACT`) |
| `max-width: 620px` | Compact composer and starters |
| `max-height: 600px` | Short-viewport hero clamp |
| `prefers-reduced-motion` | Motion and typewriter off |

There is no `min-width` desktop breakpoint above 860px — the layout is fluid
above it, capped by `--reading-width`.
