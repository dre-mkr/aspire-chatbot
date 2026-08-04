# P6 — Delivery: bundle, assets, network

Diagnosis and proposals. **Nothing applied.** Module attribution comes from a
sourcemap build (`vite build --sourcemap`) parsed byte-by-byte, not from
guesswork about chunk names.

---

## 1. Chunk map, with contents

| Chunk | raw | gzip | What is actually in it |
|---|---|---|---|
| `index-D_m1NPoL.js` | 257.6 KB | 80.3 KB | react-dom 170.7, seroval 21.3, react-router 17.5, query-core 10.8, router-core 9.1, start-client-core 7.2, scheduler 3.4 |
| `_shell-CAGyYKn_.js` | 115.4 KB | 34.3 KB | **all application code**: WordScramble 10.3, EligibilityCheck 10.3, TrueFalse 10.2, Transcript 9.8, icons 9.1, AspireChat 7.7, use-conversation 7.6, Rail 6.7, Voice 6.6, VoiceSettings 5.0, use-voice 4.9 |
| `query-NESHdaTQ.js` | 62.2 KB | 19.8 KB | router-core 37.3, query-core 14.8, react-router 5.6, history 4.1 |
| `session-r0bm5HTK.js` | 33.6 KB | 11.8 KB | router-core 16.3, react 7.8, react-dom 3.4, session.ts 2.2 |
| `styles-DRB-mjzC.css` | 76.4 KB | 14.8 KB | Tailwind 4 output, single file |
| auth route chunks (6) | ~19 KB | ~8 KB | signup 7.0, Field 4.1, AuthSurface 3.3, signin 2.3, auth 2.0, reset 1.7, verify 1.1 |

**First load (chat route): 545.2 KB raw / 160.9 KB gzip / 140.5 KB brotli.**

### Ten largest modules, and whether each earns its place

| # | Module | raw | Justified? |
|---|---|---|---|
| 1 | `react-dom` | 174.1 KB | **Yes.** Unavoidable; 32% of the bundle. |
| 2 | `@tanstack/router-core` | 62.8 KB | **Yes**, but spread across 3 chunks (37.3 + 16.3 + 9.1) — see §4. |
| 3 | `@tanstack/query-core` | 32.1 KB | **Yes.** |
| 4 | `@tanstack/react-router` | 25.0 KB | **Yes.** |
| 5 | `seroval` | 21.3 KB | **Yes, but worth a second look.** It serialises SSR state for Start. P4 found the Query dehydration path is *inert* (every query is gated on a client-only session, so nothing is ever dehydrated). seroval is still needed by Start's own plumbing, so it cannot simply be dropped — but 21 KB is being paid for a mechanism the app does not currently use. |
| 6 | `WordScramble.tsx` | 10.3 KB | **No — should be lazy.** |
| 7 | `EligibilityCheck.tsx` | 10.3 KB | **No — should be lazy.** |
| 8 | `TrueFalse.tsx` | 10.2 KB | **No — should be lazy.** |
| 9 | `Transcript.tsx` | 9.8 KB | **Yes.** Core surface. |
| 10 | `icons.tsx` | 9.1 KB | Marginal. One eager module holding every icon in the product. |

---

## 2. The finding that dwarfs the rest: nothing is compressed

`deploy/nginx-aspire.conf` contains **zero `gzip` or `brotli` directives** —
verified by `grep -ciE "gzip|brotli"` returning `0`. The deploy README never
mentions compression either.

This is not merely "brotli is missing". Two nginx defaults make it worse:

- **`gzip_types` defaults to `text/html` only.** So even if the distro's
  `/etc/nginx/nginx.conf` sets `gzip on;` in its http block — which Debian and
  Ubuntu do — **JavaScript and CSS are still served uncompressed**, because
  nothing ever widens `gzip_types`.
- **`gzip_proxied` defaults to `off`.** The SSR document is proxied from Node on
  :3000, so nginx will not compress it either.

Measured cost, on the actual first-load assets:

| | raw | gzip | brotli |
|---|---|---|---|
| First load total | **545.2 KB** | 160.9 KB | 140.5 KB |
| Saving vs today | — | **384 KB (70%)** | **405 KB (74%)** |

Brotli is a further 20.4 KB (13%) better than gzip.

On the pack's target — p75 mid-tier Android, throttled Fast 3G (~400 Kbps
effective) — 384 KB is roughly **7-8 seconds of additional transfer on every
cold load**. No code change is required; this is a config fix.

**Note:** `vite preview` *does* gzip, which is why local testing looks fine. That
server is not in the production path. nginx is.

### Proposal

```nginx
gzip on;
gzip_vary on;
gzip_proxied any;                      # so the SSR document is compressed too
gzip_min_length 1024;
gzip_types application/javascript text/javascript text/css application/json
           image/svg+xml application/manifest+json;
# and, if ngx_brotli is available:
brotli on;
brotli_types <same list>;
brotli_static on;                      # pre-compressed .br from the build
```

**Predicted saving: 384 KB per cold load (gzip) or 405 KB (brotli).**

---

## 3. What should be lazy and is not

`_shell` carries the entire application, including three interactive surfaces
most sessions never open:

| Module | raw | Loaded when? | Should be |
|---|---|---|---|
| `WordScramble.tsx` | 10.3 KB | always | on `start_game` |
| `TrueFalse.tsx` | 10.2 KB | always | on `start_game` |
| `EligibilityCheck.tsx` | 10.3 KB | always | on `start_eligibility_check` |
| **games + eligibility** | **30.8 KB** | | **~9 KB gzip off first load** |
| `Voice.tsx` | 6.6 KB | always | when `voice_enabled` |
| `VoiceSettings.tsx` | 5.0 KB | always | on opening settings |
| `use-voice.ts` | 4.9 KB | always | when `voice_enabled` |
| **voice** | **16.5 KB** | | **~5 KB gzip off first load** |

Voice is behind a **server-side** flag (`VOICE_ENABLED`), fetched at runtime via
`/api/voice/config`. When that flag is off, 16.5 KB of voice code ships to every
user and is never executed.

All three card surfaces render only in response to a server-driven turn
(`game_started` / `eligibility_started`), which is a natural `React.lazy`
boundary — the card is already rendered asynchronously after a network round
trip, so a chunk fetch adds no perceptible delay.

**Predicted saving: ~47 KB raw / ~14 KB gzip off the first load.**

### Locales — not a finding

ES and FR strings *are* shipped to English users, but they are a handful of
inline object literals (`GAME_TITLES`, `ELIGIBILITY_TITLES`, a few in
`WordScramble`) totalling a few hundred bytes. There is no i18n library and no
per-locale bundle to split. Splitting these would cost more in complexity than it
returns. (That the UI chrome has *no* translation system at all is a P10 concern,
not a delivery one.)

---

## 4. Duplicates

**One real duplicate, at two versions:**

```
@tanstack/store      0.9.3   node_modules/@tanstack/react-router/node_modules/@tanstack/react-store/node_modules/@tanstack/store
@tanstack/store      0.11.0  node_modules/@tanstack/store
@tanstack/react-store 0.9.3  node_modules/@tanstack/react-router/node_modules/@tanstack/react-store
@tanstack/react-store 0.11.0 node_modules/@tanstack/react-store
```

`@tanstack/react-router` pins its own nested `react-store@0.9.3`; the project
separately declares `0.11.0` at the top level, which **nothing imports** (P4-009).

**This resolves P4-009:** the top-level declarations are genuinely unused and can
be removed — react-router keeps its nested copy regardless. The `optimizeDeps`
workaround in `vite.config.ts:24-28` is targeting the *transitive* 0.9.3 copy, so
it must stay.

Bundle impact of removing them is likely **zero** (the unused 0.11.0 copy is
tree-shaken), so this is hygiene rather than weight.

**`react` and `react-dom` are NOT duplicated at runtime.** A naive count shows
"2 copies" of each, but the second is `@types/react` / `@types/react-dom` —
types, not code. No React duplication.

**`@tanstack/router-core` appears in three chunks** (37.3 + 16.3 + 9.1 KB). This
is rolldown splitting one package's modules across chunks by usage, not three
copies of the same code — the shared chunk graph is doing its job. Not a finding.

---

## 5. Tree-shaking

**Clean.** `grep -rn "import \* as"` across `src/` returns **nothing** — no
namespace imports anywhere. No barrel-file re-export modules in the app. Every
`@tanstack/*` import is a named import from a package with proper ESM exports.

The one structural observation is `icons.tsx` (9.1 KB): a single module exporting
every icon, imported by many components. Because each icon is a separate export
and the module is side-effect-free, tree-shaking *should* handle it — and the
9.1 KB attributed is what actually survived, so unused icons are presumably
already gone. Not a finding.

---

## 6. Fonts

**No `@font-face` rule exists in the built CSS** — zero occurrences. Every font
comes from the external Google stylesheet in `__root.tsx:31-41`:

```
Instrument Serif + JetBrains Mono 400 + Sora 300;400;500;600;700  (&display=swap)
```

- **Subset?** No. Full character sets for three families.
- **Preloaded?** No — `preconnect` to both origins, but no `preload` of the
  font files themselves.
- **`font-display`?** Yes, `&display=swap` in the URL. Correct.
- **FOIT/FOUT causing CLS?** **Measured in P5: no.** Fonts-blocked vs
  fonts-allowed differed by 0.0044 CLS. `display=swap` plus the fallback metrics
  are working.

So fonts are **not** a CLS problem — but they are a critical-path problem: a
render-blocking stylesheet from a third origin, requiring DNS + TLS to
`fonts.googleapis.com` and then again to `fonts.gstatic.com` before text paints.
**Sora is loaded at five weights**, which is a lot for a product that uses maybe
three.

**Proposal:** self-host subsetted `woff2` (Latin only), drop unused Sora weights,
`<link rel="preload" as="font" crossorigin>` the two used in the first paint, and
delete both preconnects. Removes two third-party origins from the critical path
— and resolves the privacy half of P3-003 at the same time.

---

## 7. Images and icons

Total `public/` is **125 KB** across 10 files. Largest is
`android-chrome-512x512.png` at 44 KB (a manifest icon, never on the critical
path). The two brand assets actually rendered are small: `aspire-mark.png` 9.3 KB,
`aspire-wordmark.png` 4.6 KB.

Explicit dimensions are set almost everywhere — `Rail.tsx:85` (40×40),
`Rail.tsx:91-96` (190×48), `Avatar.tsx:33-35` (width + height + style).

**One gap: `AuthSurface.tsx:62-65` renders the wordmark with `src` and `alt` but
no `width`/`height`** — an unreserved box on the sign-in, sign-up, verify and
reset pages.

No `loading="lazy"` anywhere, which is **correct**: every rendered image is a
small above-the-fold brand mark, and lazy-loading those would delay them.

PNG → WebP would save perhaps 5-6 KB combined. Marginal; listed for completeness.

---

## 8. Caching — correct

| Path | Policy | Verdict |
|---|---|---|
| `/assets/` | `expires 1y` + `Cache-Control: public, immutable` | ✅ Correct — filenames are content-hashed. |
| `/brand/` | `expires 7d` + `public` | ✅ Reasonable for unhashed assets. |
| favicons, manifest | `expires 7d` + `public` | ✅ |
| SSR document | proxied, no explicit cache header | ✅ Correct — must not be cached. |

The build/deploy story is genuinely good: `update.sh` builds into a second slot
and swaps a symlink in one `rename`, so a deploy is atomic and a failed build
leaves the previous bundle serving. Hashed filenames make staleness impossible.

**Caching is the one delivery area that needs no work.**

---

## 9. Third-party scripts

Enumerated from the built output — every external origin referenced:

| Origin | Purpose | Blocks? | Cost |
|---|---|---|---|
| `fonts.googleapis.com` | font CSS | **Yes** — render-blocking stylesheet | DNS + TLS + request |
| `fonts.gstatic.com` | font files | No (swap) | DNS + TLS |
| `react.dev`, `tailwindcss.com`, `w3.org`, `cdn.example.com` | strings in comments/docs/schema URLs | No | 0 |

**There are no analytics, tag managers, session recorders, ad scripts or
trackers of any kind.** For a government product serving minors that is exactly
right, and worth recording explicitly — it is the kind of thing that gets added
later without much thought.

The only genuine third party is Google Fonts, addressed in §6.

---

## 10. Network waterfall and the critical path

Cold load, chat route:

```
1. GET /                      SSR document, 10.5 KB, ~400ms observed locally
2. (parallel) preconnect fonts.googleapis + fonts.gstatic
3. GET fonts.googleapis.com/css2   ← RENDER-BLOCKING, third origin
4. GET /assets/styles.css          ← render-blocking, 76 KB uncompressed
5. GET /assets/index.js + _shell.js + query.js + session.js   ← 469 KB uncompressed
6. hydrate
7. POST /api/auth/anonymous        ← client-only, gated behind hydration
8. GET /api/conversations          ← gated behind (7)
```

Two serial chains that could be shortened:

- **Steps 7→8 are strictly serial and cannot start until hydration completes**,
  because every query is gated on `currentSession()` which is client-only (P4 §8).
  So the rail is empty until: document → JS download → parse → hydrate → auth
  round trip → list round trip. Nothing is dehydrated into the document to cover
  that gap.
- **Step 3 is a third-party render-blocking request** that steps 4-5 do not
  depend on but the first paint does.

**Critical path to first token** is unchanged by any of this — it is dominated by
the backend (P0-001: the client waits for the entire model response before the
typewriter starts). Delivery work will improve first *paint*, not first *token*.

---

## 11. Proposed changes, ranked by value per unit of effort

| # | Change | Predicted saving | Effort | Risk |
|---|---|---|---|---|
| 1 | **nginx gzip + brotli** (§2) | **384-405 KB per cold load** | config only | very low |
| 2 | Lazy games + eligibility cards (§3) | 30.8 KB raw / ~9 KB gzip | small diff | low |
| 3 | Lazy voice behind its flag (§3) | 16.5 KB raw / ~5 KB gzip | small diff | low |
| 4 | Self-host subsetted fonts, drop Sora weights (§6) | 2 origins + 1 blocking request off the critical path | medium | low — also fixes P3-003 privacy |
| 5 | `width`/`height` on `AuthSurface` wordmark (§7) | CLS on 4 auth routes | 1 line | none |
| 6 | Drop unused `@tanstack/store` / `react-store` (§4) | ~0 KB (hygiene) | 2 lines | low |
| 7 | PNG → WebP for brand marks (§7) | ~5 KB | small | none |

Item 1 alone is worth more than every other delivery change in this report
combined, and it is the cheapest.

**Actual deltas to be measured after P11**, per the pack.

---

## 12. Summary

**6 findings: 1 × S1, 3 × S2, 2 × S3.**

**Worst — P6-001 (S1):** nothing is compressed in production. 545 KB of
first-load assets go over the wire raw. nginx has no `gzip`/`brotli` directives,
and the two defaults that matter (`gzip_types` = html-only, `gzip_proxied` = off)
mean an inherited `gzip on;` would not save JS, CSS, or the SSR document either.
384 KB per cold load, fixable in config.

The rest of the delivery story is better than expected: caching is correct and
the atomic symlink deploy is genuinely well built, tree-shaking is clean with no
namespace imports anywhere, route splitting works, React is not duplicated, there
is exactly one real duplicate package (and it resolves an open P4 question), fonts
are measurably *not* a CLS source, images mostly carry explicit dimensions, and
there is not a single analytics or tracking script in the product.
