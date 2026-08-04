# P3 — TanStack Start + Router audit

Diagnosis only. No production code was changed.

**One process note.** To answer "is the route tree generated or hand-edited?" I
backed up `routeTree.gen.ts`, ran `tsr generate`, diffed, and **restored the file
byte-for-byte** (verified with `diff -q`). That regeneration is itself how
P3-001 was found. The working tree is exactly as I found it.

---

## 1. The S0 check: server-only boundary — **clean**

Scanned the built client bundle (`dist/client/`) for:

- secret shapes: `sk-…`, `sk_live_…`, `postgres://`, `redis://`, `rediss://`,
  `eyJ…` (JWT), `AIza…`, `xoxb-…` → **no matches**
- server module names: `langchain`, `langgraph`, `chromadb`, `asyncpg`,
  `sqlalchemy`, `SESSION_SECRET`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `ELEVENLABS_API_KEY`, `DATABASE_URL`, `VALKEY_URL` → **no matches**

**No S0.** The boundary holds, and it holds for a structural reason: the frontend
never talks to the database, the model, or any provider SDK. It speaks HTTP to
the FastAPI service and nothing else. There are no server functions at all (see
§4), so there is no server/client boundary to leak across.

DevTools are also correctly stripped: `TanStackDevtools` and
`TanStackRouterDevtoolsPanel` are imported unconditionally in `__root.tsx:76-85`,
but `[@tanstack/devtools-vite] Removed devtools code from: /src/routes/__root.tsx`
appears in the build log and neither symbol appears in `dist/client/`. Verified,
not assumed.

---

## 2. Routing

### Route tree — **drifted, and the drift is a booby trap (P3-001)**

`src/routeTree.gen.ts` ends with ten lines that `tsr generate` does **not**
produce:

```ts
import type { getRouter } from './router.tsx'
import type { startInstance } from './start.ts'
declare module '@tanstack/react-start' {
  interface Register {
    ssr: true
    router: Awaited<ReturnType<typeof getRouter>>
    config: Awaited<ReturnType<typeof startInstance.getOptions>>
  }
}
```

That block is load-bearing: it registers the router type with `@tanstack/react-start`
and is the **only place `ssr: true` is declared in the entire app**. It lives in a
file whose header says it is generated, and `npm run generate-routes` deletes it.

This is not hypothetical — I reproduced it and had to restore the file.

### Search and route params — **validated everywhere they exist**

| Route | Params | Validation |
|---|---|---|
| `_shell` | `simple` | `validateSearch` coerces `true`/`"true"`, discards anything else |
| `signin` | `next` | `validateSearch` → `safeNext` |
| `signup` | — | `validateSearch` present |
| `verify` | — | `validateSearch` present |
| `reset` | — | `validateSearch` present |
| `_shell/chat/$chatId` | `chatId` | path param, read raw — but see below |

All five search-param routes validate. They use hand-written validator functions
rather than a schema library, which is legitimate — `validateSearch` returning a
narrowed type *is* the contract, and `zod` is not in the tree (P2).

`chatId` is read raw, which I chased because it flows into a URL path. It is
**correctly escaped**: `conversations.ts:110,121` use
`encodeURIComponent(threadId)`. No path-traversal or injection vector. Not a
finding.

### Open redirect — **properly closed** (worth recording)

`signin.tsx` `safeNext` rejects anything not starting with `/` and rejects
protocol-relative `//`. It is applied **twice** — once in `validateSearch`, again
at the `navigate` call — with a comment explaining exactly why ("the value that
matters is the one handed to `navigate`"). This is the strongest single piece of
security reasoning I have seen in this codebase.

One residual: `/\evil.com` passes both checks (starts with `/`, not `//`), and
some browsers normalise `/\` to `//`. Here the value goes to the router's `to`,
which resolves it as an internal route rather than a location assignment, so the
practical risk is low. Hardening only — P3-007.

### State that belongs in the URL — **language is the gap**

| State | Where it lives | Verdict |
|---|---|---|
| Active conversation | `/chat/$chatId` | ✅ in the URL |
| Simple mode | `?simple=true` on `_shell` | ✅ in the URL |
| **Language (EN/ES/FR)** | `useState` in `use-voice.ts:114`, persisted to localStorage | ❌ **P3-004** |
| **Persona** | prop on `AspireChat`, never passed | ❌ **P3-005** |
| Open panel / modal | component state | fine — not shareable state |

Nothing inappropriate is in the URL: no secrets, no high-churn values, no history
spam. `simple` is a genuine shareable toggle and belongs there.

**Language (P3-004)** is device-scoped, not conversation-scoped. Conversations are
stored server-side *with* a `language` column (`ensure_conversation(language=…)`),
so a conversation held in French reopens in whatever language the device is set
to. Sharing a conversation link cannot carry its language.

The SSR handling of it is correct — `DEFAULT_PREFS` on the server, real
preferences read from localStorage in a mount effect (`use-voice.ts:132-138`),
which is the right pattern and avoids a hydration mismatch. But it has a visible
consequence: **every load paints in English first, then swaps** once the effect
runs. For a Spanish or French user that is a language flash on every single page
load.

**Persona (P3-005)** is worse than "not in the URL": it is not wired at all.
`AspireChat` accepts `persona?: GamePersona | null` and is called in exactly one
place — `_shell.tsx:17`, as `<AspireChat />`, with no props. So `persona` is
**always `null`**. There is no picker anywhere in the client; the only persona
constant is `DEFAULT_PERSONA = "nova"` in `voice.ts:15`, used for voice selection.

The code acknowledges this (`AspireChat.tsx:63`: *"Wire a picker"*), so this reads
as unbuilt rather than broken. **But the audit brief lists "persona switch
(Stella/Orion/Aurora/Nova)" as critical path (c) — that path does not exist.**
The backend fully supports personas: prompts, per-persona voices, games config.
For a product whose premise is age-appropriate help for 5-18 year olds, every
child currently gets the same undifferentiated persona. That is a product
decision to make, not a defect to fix quietly.

### Loaders — one exists, and it is a warmer, not a loader

`_shell/chat/$chatId.tsx` is the only route with a `loader`:

```ts
loader: ({ context, params }) => {
  if (!currentSession()) return;
  void context.queryClient.ensureQueryData(conversationQuery(params.chatId))
    .catch(() => undefined);
}
```

It does not `return` or `await` the promise, so the route resolves immediately
and the document is never gated on conversation data. Given both child routes
render `() => null` and `AspireChat` does its own fetching, this is a **cache
warmer** — and a reasonable one. Calling it a loader oversells it, but it is not
wrong.

`currentSession()` is SSR-guarded (`session.ts:104`: `typeof window === "undefined"`
→ `null`), so during SSR the loader correctly no-ops. Verified rather than
assumed.

**`loaderDeps`:** not needed anywhere. The one loader depends on `params`, not
search params. Correct as written.

**Waterfalls:** cannot be assessed without the app running. Carries to P5.

### Preloading — **not the data-plan risk it looks like**

`router.tsx:13-14` sets `defaultPreload: "intent"` with `defaultPreloadStaleTime: 0`,
which normally means every hover re-runs the loader. Here it does not cost
anything, because the loader delegates to `ensureQueryData` and the queries have
deliberate stale times:

| Query | staleTime | refetch flags |
|---|---|---|
| `conversations` list | 30s | default |
| `conversation` messages | `Infinity` | `refetchOnWindowFocus: false` |
| `gameState` | `Infinity` | focus/reconnect/mount all off |
| `eligibilityState` | `Infinity` | focus/reconnect/mount all off |

So hovering rail rows repeatedly does **not** refetch. **Not a finding** — but it
is load-bearing coupling that nobody has written down: raising
`defaultPreloadStaleTime` would be harmless, while lowering any query's
`staleTime` would silently turn hover into a fetch storm.

### Pending / error / not-found — **totally absent (P3-002)**

Zero routes define `pendingComponent`, `errorComponent`, or `notFoundComponent`.
`router.tsx` sets no `defaultPendingComponent`, `defaultErrorComponent`, or
`defaultNotFoundComponent`. `__root.tsx` defines neither.

There is no error or 404 handling in this application at any level.

An unknown URL and a thrown loader error both land on TanStack Router's built-in
defaults: untranslated, developer-oriented, off-brand, and with no route back
into the app. For a government service aimed at children in three languages, that
is the wrong last line of defence. It also means the P0-004 orphaned-chat case
(committed chat, nothing persisted) has no route-level recovery.

Min-pending timing is moot until pending components exist.

### Code splitting — working

From the P0 build: `signin`, `signup`, `verify`, `reset`, `AuthSurface`, `Field`,
`session`, `query` and `_shell` are all separate client chunks. Auth code is not
in the chat path. Module-level attribution ("what is in the root chunk that
shouldn't be") needs a bundle analyzer and belongs to P6.

### Link/navigate type safety — one escape (P3-006)

Every `navigate` call uses the typed object form (`navigate({ to: "/signin", … })`),
which is type-checked. One exception: `AuthSurface.tsx:31` declares
`footLinkTo?: string` and passes it to `<Link to={footLinkTo}>` (l.145). Widening
to `string` erases the route union, so a typo compiles cleanly and lands on the
non-existent not-found handler from P3-002.

---

## 3. SSR

**Mode is never chosen per route (P3-008).** `ssr: true` is declared once,
globally, inside the fragile augmentation block from P3-001. No route sets `ssr`.
Every route inherits full SSR by default — including `signin`, `signup`, `verify`
and `reset`, which are client-interactive forms that would be equally correct as
SPA-mode routes. Nothing here is *wrong*; it is simply that no decision was made.

**What gates first paint.** The SSR document is not blocked on data — the only
loader is fire-and-forget and both child routes render `null`. The slowest thing
on the critical path is instead **`__root.tsx:31-41`: a render-blocking
stylesheet from `fonts.googleapis.com`**, requiring DNS + TLS + fetch to two
third-party origins (`googleapis` and `gstatic`) before first paint. `display=swap`
is set, so this is a latency cost rather than an FOIT cost. Quantifying it belongs
to P6 — but there is a second dimension that is not a performance question at all:

**Every child using this service makes a request to Google** carrying IP address,
user-agent and referer, on a government product for minors. That is a third-party
disclosure decision, and it needs the programme's data-protection owner to sign
it off or the fonts to be self-hosted. Recorded as P3-003 and flagged for P9.

**Hydration mismatches — none found.** I chased all three candidates:

- `WordScramble.tsx:167` `Math.random()` — inside the `shuffle` `useCallback`, an
  event handler. Not render.
- `signup.tsx:74` `new Date()` — inside an age-calculation helper driven by
  user-entered values on submit. Not render.
- `use-voice.ts:114` localStorage — correctly deferred to a mount effect with
  server-safe defaults.

The only hydration-adjacent issue is the *consequence* of doing it correctly: the
language flash described in P3-004.

**Server functions — there are none.** No `createServerFn` anywhere in `src/`.
Every mutation goes over `fetch` to FastAPI. So "is every server function
input-validated?" has no call sites, and the boundary-leak question is answered
structurally (§1). This is a coherent architecture — Start is being used as an
SSR renderer and router, not as a backend — but it does mean the client validates
nothing it receives (P2-003) and the `VITE_ASPIRE_API_URL` origin is baked into
the client bundle.

**`_shell` layout across the transition — structurally sound.** `_shell.tsx:16-20`
renders `<AspireChat />` **beside** `<Outlet />`, not inside it. Both child routes
render `null`. So navigating `/` ⇄ `/chat/:id` changes only what the (empty)
Outlet renders — `AspireChat` never unmounts, and all conversation state survives
by construction. This is the cleanest answer to the pack's question, and it is
achieved by architecture rather than by careful memoization.

CLS and frame timing across the compositor→dock transition **cannot be measured
without the app running**. Carries to P5.

**Deployment target — matches.** `vite build` emits `dist/server/server.js`
exporting a Web-standard fetch handler; `server.mjs` binds it with srvx on
`127.0.0.1:3000`; nginx proxies to it and serves `dist/client/` directly; systemd
supervises. No adapter/preset is configured and none is needed. Nothing depends
on a Node API unavailable in the target — it is plain Node 26 on a VPS with the
full surface. Confirmed consistent end to end.

---

## 4. Summary

**8 findings: 0 × S0, 0 × S1, 4 × S2, 4 × S3.**

The S0 hunt came back clean, and for a structural reason worth stating: this
frontend has no server functions and no server SDKs, so there is no boundary to
leak across.

**Worst finding: P3-002** — the application has no error, pending, or not-found
handling at any level. Every other finding in this pass is a decision that was
not made; this one is a missing floor.

**Most dangerous finding: P3-001** — `routeTree.gen.ts` carries hand-written type
registration, including the app's only `ssr: true` declaration, in a file that
`npm run generate-routes` overwrites. I triggered it during this audit and had to
restore the file.

**The finding that most affects the product: P3-005** — the four ASPIRE personas
are fully supported by the backend and cannot be selected in the UI, because
`AspireChat`'s `persona` prop is never passed. The audit brief lists persona
switching as a critical path; it is not built.

Recorded as verified-sound so later passes do not re-derive them: the client
bundle is clean of secrets and server modules, DevTools are stripped, the open
redirect is properly closed and double-checked, `chatId` is escaped,
`currentSession()` is SSR-guarded, there are no hydration mismatch sources,
navigation is typed everywhere but one prop, the preload/staleTime interaction is
safe, the layout genuinely does not remount across the shell transition, and the
deployment target matches the built artifact.
