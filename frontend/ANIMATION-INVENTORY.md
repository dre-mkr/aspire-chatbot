# Animation inventory — empty state → first message → streaming

Everything that moves on the send path, with component, trigger, duration and
easing. Written before any routing change, so the Phase 2 result can be checked
against it.

**Read this first:** the transition from empty state to conversation is **not an
enter/exit animation**. It is one attribute — `data-phase` on `.app` — flipping
seven custom properties, with each consumer transitioning the property it cares
about on its own schedule. Nothing mounts and nothing unmounts. The hero, the
composer and the starters are all present in both phases; only their computed
values differ.

That is why this is fragile under routing. **Any change that unmounts the
subtree replaces a coordinated 560ms morph with a hard cut**, and no
`layoutId` or View Transition reproduces it, because there is no element
travelling from A to B — there are eight properties interpolating at once.

## Shared tokens

| Token | Value | Meaning |
|---|---|---|
| `--ease` | `cubic-bezier(0.4, 0, 0.2, 1)` | Everything except the game tiles |
| `--swift` | `150ms` | Hover, press |
| `--settle` | `300ms` | State change |
| `--morph` | `560ms` | **The phase change** |

## 1. The phase morph — `landing` → `chat`

Trigger: `data-phase` on `.app` flips when `send()` sets `phase = "chat"`.

| # | Element | Property | Duration / easing | Landing → chat |
|---|---|---|---|---|
| 1 | `.stage` | `grid-template-rows` | `560ms --ease` | `0.7fr` → `0fr` (starters row collapses) |
| 2 | `.hero` | `opacity` | `380ms --ease` | `1` → `0` |
| 3 | `.hero` | `max-height` | `560ms --ease` | `min(380px, 44vh)` → `0px` |
| 4 | `.composer` | `min-height` | `560ms --ease` | `min(168px, 22vh)` → `112px` |
| 5 | `.composer__field` | `grid-template-rows` | `560ms --ease` | `min(96px, 12vh)` → `46px` |
| 6 | `.rail` | `width`, `min-width` | `480ms --ease` | `0px` → `272px` |
| 7 | `.rail` | `border-color` | `300ms --ease` | `transparent` → `--hairline` |
| 8 | `.workspace` | `background` | `560ms --ease` | `transparent` → `rgb(255 255 255 / 0.97)` |
| 9 | `.topbar` | `color` | `560ms --ease` | `rgb(255 255 255 / 0.95)` → `--prose` |
| 10 | `.atmosphere` | `animation-play-state` | instant | `running` → `paused` |

These ten run **concurrently from a single attribute change**. The staggering is
deliberate: the hero fades (380ms) before its height finishes collapsing
(560ms), and the rail arrives slightly early (480ms), so the composer appears to
settle last.

## 2. Entry animations on the first message

| # | Element | Keyframe | Duration / easing | Trigger |
|---|---|---|---|---|
| 11 | `.turn` (user bubble, assistant turn) | `rise` — `opacity 0→1`, `translateY(12px)→0` | `400ms --ease both` | Each message mounting |
| 12 | `.follow-ups` | `rise` | `400ms --ease both` | Follow-ups appearing after a settled answer |
| 13 | `.thinking__dots i` | `dot-pulse` | `1.2s ease-in-out infinite` | While `isThinking` |
| 14 | `.orb--thinking` | `orb-glow` | `1.6s ease-in-out infinite` | While `isThinking` |
| 15 | `.sources`, `.game`, `.voice-note`, `.voice-consent` | `rise` / `pop-in` | `220–300ms --ease both` | On mount |

## 3. The streaming reveal (JavaScript, not CSS)

`use-conversation.ts`:

| Constant | Value | Effect |
|---|---|---|
| `TICK_MS` | `40` | 25 ticks per second |
| `WORDS_PER_TICK` | `4` | 100 words/sec in prose |
| `TICKS_PER_ITEM` | `3` | List items land every 120ms |

Held in `streaming` state **outside** `messages`, so a tick re-renders only the
one revealing component. `prefersReducedMotion()` bypasses the whole reveal and
settles the answer in a single frame.

## 4. Ambient (running throughout)

| Element | Keyframe | Duration |
|---|---|---|
| `.atmosphere span` ×4 | `drift-a` / `drift-b` / `drift-c` | `30s`–`48s` infinite; **paused in chat** |
| `.orb--hero` | `orb-float` | `6s` infinite |
| `.orb--hero::before` | `orb-glow` | `4.5s` infinite |

## 5. Reduced motion

Scoped, not blanket. Ornamental animation is killed; entrances collapse to their
final frame (`animation-duration: 1ms`); all transitions become `1ms`. Three
survive deliberately — `.thinking__dots` (`dot-fade`), `.voice-spinner`, and the
recording dot — because they are the only evidence that something is happening.

---

# What this means for Phase 2

The requirement is that `/` and `/chat/$chatId` differ **only in params, not in
tree**. Concretely, across the transition these must all hold:

1. `.app` is the same DOM node — otherwise all ten phase transitions restart
   from their `chat` values instead of interpolating from `landing`.
2. `.hero` is never unmounted — otherwise it disappears instantly instead of
   fading over 380ms while collapsing over 560ms.
3. `.composer` is the same node — otherwise `min-height` jumps `168px → 112px`
   with no interpolation, and the input visibly snaps.
4. `.rail` is the same node — otherwise it appears at full 272px instead of
   widening over 480ms.
5. The user's `.turn` plays `rise` **once**, on mount. A remount replays it,
   which reads as the message being sent twice.

**Plan:** a pathless layout route owns `AspireChat` and both `/` and
`/chat/$chatId` resolve into it, so navigating between them changes params only.
First send uses `navigate({ replace: true })`. Nothing in the list above
unmounts.

**Escape hatch not taken:** Framer Motion `layoutId` / the View Transitions API
would be the fallback if the shared-layout approach failed. It is not installed,
and reaching for it would mean the tree is being torn down — the thing this
inventory says must not happen. If I end up needing it I will stop and say so.

## How this gets verified

Not by eye. `.impeccable/anim-check.mjs` records, across the first send:

- the identity of `.app`, `.hero`, `.composer`, `.rail` before and after
  (via a stamped attribute), asserting the same node survives;
- a per-frame sample of `.hero` opacity/height, `.composer` min-height and
  `.rail` width, asserting each moves through **intermediate values** rather
  than jumping;
- the number of times `rise` runs on the first user turn (must be exactly 1);
- total frames and the largest single-frame delta, to catch a dropped frame.
