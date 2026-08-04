# P5 — Chat surface performance

**Measured, not reasoned.** Every number below comes from the **production
build** (`vite preview`) driven in real Chrome via Puppeteer, with the API mocked
at the network layer — so this exercises the shipped React tree and cost nothing
in OpenAI tokens. No production code was changed.

Harnesses: `scratchpad/p5-profile.mjs` (scaling, frames, long tasks, memory) and
`scratchpad/p5-anchor.mjs` (CLS attribution, scroll anchoring).

**This pass also closes the P0 blocker: `reports/baseline-screens/` now holds 14
screenshots at 375px and 1440px across seven states.** The UI-change policy has a
pixel contract from here on.

---

## 0. Two things I got wrong by reading, and the measurements that corrected them

Worth stating first, because both were about to become findings.

**1. "No `memo()` in Transcript, so the whole list re-renders per tick."** False.
`grep` finds no `memo(`/`useMemo` in `Transcript.tsx` — but `vite.config.ts:59`
enables `babel-plugin-react-compiler`, and the shipped chunk containing
Transcript's markup (`_shell-CAGyYKn_.js`) carries **391 memo-cache comparison
sites**. The compiler memoizes it automatically. Source-reading gave the opposite
of the truth.

**2. "Google Fonts are a CLS source" (speculated in P3).** False. Measured with
fonts blocked vs allowed:

| | fonts blocked | fonts allowed |
|---|---|---|
| Landing | CLS 0.0003 | CLS 0.0044 |
| Restore a conversation | CLS 0.3510 | CLS 0.3605 |

Fonts contribute **~0.004** — immaterial. `display=swap` plus the fallback stack
is doing its job. The P3 font finding stands on privacy and latency grounds only;
**the CLS half of it is withdrawn.**

---

## 1. Streaming render

There is no streaming (P0-001). The reveal is a `setInterval(tick, 40ms)` over an
already-complete, already-parsed reply. So the pack's chunk questions resolve as:

**Is markdown re-parsed from the full buffer every chunk? No — and it wouldn't
matter if it were.** `parseAnswer` runs **once** per reply
(`use-conversation.ts:717`); the typewriter slices pre-parsed blocks. Measured
cost of the parser itself:

| Reply length | `parseAnswer` | per 1k chars |
|---|---|---|
| 500 chars | 0.0078 ms | 0.0156 |
| 5,000 | 0.0128 ms | 0.0026 |
| 10,000 | 0.0289 ms | 0.0029 |
| 20,000 | 0.0589 ms | 0.0029 |
| 50,000 | 0.1195 ms | 0.0024 |

Flat per-1k from 5k upward — **linear, not quadratic**. And the hypothetical
O(n²) shape the pack warns about would cost **4.3 ms total** across all ~432
ticks of a 10k reply. `parseInline` over an entire 10k-char reply is 0.28 ms.

**The parser is not a performance problem at any realistic size.** That question
is closed.

**Is chunk handling batched to animation frames?** Neither — it is a 40 ms
`setInterval`, i.e. ~25 commits/second, unsynchronised with the display's 60 Hz
refresh. Every tick calls `setStreaming({...})` with a fresh object and a fresh
`blocks` array. A `requestAnimationFrame` drive would align these; measured frame
p50 is 16.7 ms (vsync) in every scenario, so the misalignment is not currently
visible in the numbers.

**No syntax highlighting, KaTeX, or heavy transform exists in this path.** The
renderer handles paragraphs, lists, bold and links only. Nothing to defer.

### What actually re-renders — measured

Long tasks recorded **during the reveal only** (observers reset immediately
before send):

| Transcript size | frames >50 ms | long tasks | total blocking | worst task |
|---|---|---|---|---|
| 0 msgs | 1 | 0 | 0 ms | — |
| 50 | 0 | **0** | **0 ms** | — |
| 200 | 1 | 1 | 76 ms | 76 ms |
| 500 | 1 | 1 | 190 ms | 190 ms |
| 2,000 | 4 | 3 | 968 ms | **863 ms** |
| 500 @ 4× CPU | 7 | 3 | 1,114 ms | **999 ms** |

**The typewriter does not re-render the whole list per tick.** A reveal runs
~200 ticks; if each re-rendered 500 messages we would see ~200 long tasks, not
one. The React Compiler's memoization is holding: settled turns bail out because
their `message` objects are referentially stable.

**But `messages` identity changes exactly twice per turn** — appending the user
bubble, and `finishStream` appending the settled answer. Each rebuilds `turns`
(`Transcript.tsx:119-130`) and re-runs the map over every message. That is where
the 190 ms and 863 ms tasks come from: **two O(N) commits per turn**.

So the S1 is real but the mechanism is not the one the pack assumes. It is not
per-chunk cost; it is **per-turn cost proportional to conversation length**.

---

## 2. Virtualization

**None.** DOM nodes scale linearly — 17 nodes per turn, exactly as an unvirtualized
list does:

| Messages | DOM nodes | JS heap | heap/turn |
|---|---|---|---|
| 0 | 136 | 5.9 MB | — |
| 50 | 996 | 6.3 MB | 128 KB* |
| 200 | 3,546 | 6.7 MB | 34 KB |
| 500 | 8,646 | 13.6 MB | 28 KB |
| 2,000 | **34,146** | **68.9 MB** | 35 KB |

\* dominated by fixed app overhead at small N.

**Degradation threshold: between 50 and 200 messages.** At 50 a full reveal
produces **zero** long tasks. At 200 the first 76 ms task appears — already past
the 50 ms budget. At 500 it is 190 ms; on 4× throttled CPU, **999 ms**.

Against the budgets:

| Budget | Measured | Verdict |
|---|---|---|
| No long task > 50 ms | 76 ms @200, 190 ms @500, 863 ms @2000 | **FAIL from ~200 messages** |
| 60 fps sustained at 500+ messages | 190 ms freeze per turn (1×), 999 ms (4×) | **FAIL** |
| CLS ≤ 0.05 | 0.35 on conversation restore | **FAIL** (§3) |
| CLS ≤ 0.05 | 0.0044 on landing | **PASS** |

The remaining virtualization sub-questions (dynamic measurement, measure→layout
loops, jump-on-scroll, overscan tuning) **do not apply — there is nothing to
tune.** If virtualization is added, the correct overscan for this content is
2-3 items: turns are tall (a 662 px viewport holds roughly one and a half), so
larger overscan buys nothing and costs measurement work.

**Prepend anchoring does not apply either:** the app loads whole conversations in
one request (`fetchConversation`), with no pagination and no "load older" path,
so there is no prepend to anchor.

---

## 3. CLS — the compositor→dock transition, attributed

The pack asked specifically whether that transition causes CLS. **It does: 0.35,
seven times the budget.** Attribution, with the shifting elements named:

```
[restore a conversation]  CLS = 0.3510 across 7 shifts
   +0.0003 @ 457ms   div.account-slot
   +0.0107 @ 606ms   div.thread__inner
   +0.1974 @ 876ms   section, form.composer, div.starters   ← the dock transition
   +0.0635 @ 944ms   section, form.composer, div.starters
   +0.0436 @1017ms   section, form.composer
   +0.0201 @1044ms   section, form.composer
```

**87% of the total comes from four shifts of `form.composer` and `div.starters`
between 876 ms and 1044 ms** — the composer moving from its landing position into
the bottom dock, and the starter chips collapsing.

The landing page itself is clean (0.0044). This is entirely a transition cost, it
lands ~1 second after navigation, and it is the single largest measured budget
breach in the product.

**During the reveal, CLS is 0.0000** in every scenario. The design note in
`use-conversation.ts:82-92` — laying out sources and follow-up chips from the
first tick so they reveal in place rather than mounting at completion and growing
the turn by 53 px — **works, and the measurement proves it.** Credit where due.

---

## 4. Scroll anchoring — all three behaviours correct

The scroll container is `.thread` (measured: `scrollHeight` 24,106,
`clientHeight` 662).

| Behaviour | Measured | Verdict |
|---|---|---|
| Restore pins to bottom | 0 px from bottom after restore | ✅ |
| Streaming growth stays anchored | CLS 0.0000 during reveal; no jitter | ✅ |
| Does not yank a scrolled-up reader | scrolled to 7,231 px, sent a message; **scrollTop still 7,231 px 6.5 s later**, 16,748 px from bottom | ✅ |

The third is the hard one and it is right — the reader is left exactly where they
were while a whole answer arrives and reveals below them. **No finding here.**

Scroll restoration after a full page reload is handled by
`scrollRestoration: true` (`router.tsx:12`); I verified restore-to-bottom on a
fresh load, which is the case that matters for a chat.

---

## 5. Memory

Heap scales linearly at ~28-35 KB per turn with no super-linear term, so there is
no evidence of a leak *within* a session. But 2,000 messages = **68.9 MB of JS
heap and 34,146 DOM nodes**, all retained, because nothing is virtualized and
nothing is released.

I did **not** run the 5-minute-apart heap snapshots under continuous use that the
pack asks for; the scenarios here are single-turn. Detached-node and
listener-accumulation questions are therefore **unanswered** and should be
revisited if virtualization work happens.

---

## 6. Voice

**Cleanup is thorough.** `stopPlayback` (`use-voice.ts:307-316`) pauses the
element, nulls the ref, and **revokes the object URL**. It is called on send
(`AspireChat.tsx:520`), regenerate (530), stop (537), chat switch (664), audio end
(`use-voice.ts:355`), and several navigation points. That is better coverage than
most.

Two gaps:

**No unmount cleanup (P5-004).** No effect returns `stopPlayback` as its cleanup.
`AspireChat` never unmounts when moving between `/` and `/chat/:id` (P3), so this
is narrow — but navigating to `/signin`, `/signup`, `/verify` or `/reset` unmounts
the whole shell, and audio playing at that moment **keeps playing with its blob
never revoked**.

**TTS requests are not cancellable (P5-005).** `voice.ts:137-146` uses
`AbortSignal.timeout(20_000)` and accepts no external signal. Interrupting
playback, sending a new message, or navigating does not abort an in-flight
`/api/voice/speak`. ElevenLabs completes the synthesis and bills for it. **Same
defect class as P0-002 for chat**, in a second subsystem.

---

## 7. Summary

**5 findings: 1 × S1, 3 × S2, 1 × S3.**

**Worst — P5-001 (S1):** two O(N) commits per turn (append user, settle answer)
re-render the entire transcript. Zero long tasks at 50 messages; 76 ms at 200;
190 ms at 500; **863 ms at 2,000**; **999 ms at 500 on 4× throttled CPU**. The
50 ms long-task budget fails from roughly 200 messages, and the "60 fps at 500+
messages" budget fails outright.

**Second — P5-002 (S2):** the compositor→dock transition contributes **0.35 CLS**,
7× budget, from four shifts of `form.composer` and `div.starters` about a second
after navigation.

The good news is substantial and measured: the parser is linear and negligible,
the React Compiler really is preventing per-tick list re-renders, the reveal
itself causes **zero** layout shift, and **all three scroll-anchoring behaviours
are correct** — including the hard one, where a scrolled-up reader is left
undisturbed while an answer arrives.

**What remains unmeasured:** real-network LCP/TTFB/INP (the API was mocked and
everything served from localhost), long-session heap snapshots, and voice
behaviour end-to-end (voice was disabled in the mocks; §6 is from code). Those
need the real backend, which is the one thing I still have not run.
