# P2 — Dependency currency and doc-verified adoption

**Nothing was applied.** No manifest, lockfile, or source file was modified.

Every version below came from the npm registry (`npm view`) or the PyPI JSON API
at audit time — none from memory. Breaking-change claims came from fetched
release notes and from reading the installed packages' own metadata.

---

## 1. Security audit — clean

| Ecosystem | Tool | Result |
|---|---|---|
| npm | `npm audit --json` | **0 vulnerabilities** (info 0, low 0, moderate 0, high 0, critical 0) |
| PyPI | OSV batch query, 18 pinned packages | **No known vulnerabilities** |

**No CVE IDs to record.** This is a genuinely good result and worth stating
plainly: the dependency surface is not where this product's risk lives.

---

## 2. Currency table

### Backend — near-perfect

| Package | Installed | Latest | Gap | Class |
|---|---|---|---|---|
| `redis` | 5.3.1 | **8.1.0** | 3 majors | **DEFER — blocked, see §3** |
| `langchain-text-splitters` | 1.1.1 | 1.1.2 | patch | SAFE |
| `uvicorn` | 0.52.0 | 0.52.1 | patch | SAFE |
| `python-dotenv` | 1.2.1 | 1.2.2 | patch | SAFE |
| `fastapi` | 0.141.1 | 0.141.1 | — | current |
| `pydantic` | 2.13.4 | 2.13.4 | — | current |
| `pydantic-settings` | 2.14.2 | 2.14.2 | — | current |
| `langchain` | 1.3.14 | 1.3.14 | — | current |
| `langchain-anthropic` | 1.5.3 | 1.5.3 | — | current |
| `langchain-openai` | 1.4.1 | 1.4.1 | — | current |
| `langchain-chroma` | 1.1.0 | 1.1.0 | — | current |
| `langgraph` | 1.2.10 | 1.2.10 | — | current |
| `sqlalchemy` | 2.0.51 | 2.0.51 | — | current |
| `asyncpg` | 0.31.0 | 0.31.0 | — | current |
| `pgvector` | 0.5.0 | 0.5.0 | — | current |
| `alembic` | 1.18.5 | 1.18.5 | — | current |
| `arq` | 0.28.0 | 0.28.0 | — | current |
| `elevenlabs` | 2.60.0 | 2.60.0 | — | current |
| `fastembed` | 0.8.0 | 0.8.0 | — | current |
| `num2words` | 0.5.14 | 0.5.14 | — | current, but **stale upstream** (§6) |
| `python-multipart` | 0.0.32 | 0.0.32 | — | current |
| `pyyaml` | 6.0.3 | 6.0.3 | — | current |

18 of 22 backend packages are at the exact latest release, all pinned with `==`.

### Frontend

| Package | Installed | Latest | Gap | Class |
|---|---|---|---|---|
| `typescript` | 6.0.3 | **7.0.2** | 1 major | **MECHANICAL** (§4) |
| `@types/node` | 22.20.1 | **26.1.2** | 4 majors | MECHANICAL |
| `srvx` | 0.11.22 | 0.12.5 | 1 minor (0.x) | MECHANICAL (§5) |
| `@biomejs/biome` | 2.4.5 | 2.5.6 | 1 minor | MECHANICAL |
| `@tanstack/react-start` | 1.168.34 | 1.168.35 | patch | SAFE |
| `@vitejs/plugin-react` | 6.0.4 | 6.0.5 | patch | SAFE |
| `@tanstack/react-router` | 1.170.18 | 1.170.18 | — | current |
| `@tanstack/react-query` | 5.101.4 | 5.101.4 | — | current |
| `@tanstack/react-router-ssr-query` | 1.167.1 | 1.167.1 | — | current |
| `@tanstack/router-cli` | 1.167.21 | 1.167.21 | — | current |
| `@tanstack/ai-client` | 0.22.1 | 0.22.1 | — | current, **but dead code** (P0-001) |
| `@tanstack/react-store` / `store` | 0.11.0 | 0.11.0 | — | current |
| `@tanstack/intent` | 0.3.6 | 0.3.6 | — | current |
| `react` / `react-dom` | 19.2.8 | 19.2.8 | — | current |
| `vite` | 8.2.0 | 8.2.0 | — | current |
| `tailwindcss` / `@tailwindcss/vite` | 4.3.3 | 4.3.3 | — | current |
| `babel-plugin-react-compiler` | 1.0.0 | 1.0.0 | — | current |
| `@rolldown/plugin-babel` | 0.2.3 | 0.2.3 | — | current |
| `puppeteer` | 25.4.0 | 25.4.0 | — | current |
| `@tanstack/react-virtual` | **not installed** | 3.14.9 | — | removed in `06074cb` |

**Note on the `"latest"` specifiers (P0-006).** The eight packages pinned to the
literal string `"latest"` all currently resolve to the true latest release. That
is luck, not policy: the lockfile is what is holding them steady, and the next
clean install can move them without review. P2 does not change the P0-006
recommendation — pin them to the versions in this table.

---

## 3. The headline: `redis` cannot be upgraded — `arq` blocks it

```
arq 0.28.0  requires  redis[hiredis]<6,>=4.2.0
```

`redis==5.3.1` is therefore the **maximum installable version**, and 8.1.0 is
unreachable while `arq` is in the tree. This is a hard resolver constraint, not a
risk assessment — attempting the upgrade produces an unsatisfiable tree.

**`arq` is not abandonware.** Latest release 0.28.0 on **2026-04-16**, which is
the version installed. The `<6` pin is a current, deliberate upstream constraint.

**`arq` is load-bearing and cannot simply be dropped.** `app/jobs.py:99-100`
registers `cron(retention_job, hour=3, minute=15)` — the job that deletes
anonymous conversations after `ANONYMOUS_RETENTION_DAYS` (180). That is a
**published privacy commitment** in `backend/PRIVACY.md`, for a product serving
minors. Removing arq to unblock a Redis upgrade would delete the enforcement of a
data-protection promise. Do not do it.

**What we forgo by staying on redis 5.x**, from the fetched 8.0 release notes:

- **Default `socket_timeout` / `socket_connect_timeout` of 5s.** `app/cache.py:93`
  carries a comment describing exactly the problem this fixes: *"redis-py sets no
  connect timeout, so it waited out the dead address"*. redis-py 8 would fix that
  by default. Until then the explicit timeout in `cache.py` is doing necessary
  work and must not be removed.
- RESP3 as the default protocol (~84 commands affected; legacy response shapes
  preserved by default).
- `max_connections=100` default and 10-attempt retry with exponential jitter.

That last one is worth flagging for when the upgrade does become possible: a
best-effort cache with 10 retries and backoff on the request path would convert
"Valkey is down" into a long stall. `app/cache.py` would need an explicit
`retry` policy at that point. **Record this now so it is not discovered later.**

**Verdict: DEFER.** Re-evaluate when arq widens its pin. Track
`arq`'s dependency constraint, not `redis`'s version number — the latter is not
the blocker.

---

## 4. TypeScript 6.0.3 → 7.0.2 — **MECHANICAL, not RISKY**

Source: the official TypeScript 7.0 announcement. TS 7 is the **native Go port**,
8-12x faster, with shifted defaults.

I checked every documented breaking change against `frontend/tsconfig.json`:

| TS 7 breaking change | This project | Verdict |
|---|---|---|
| `strict` now default | already `"strict": true` (l.22) | no-op |
| `module` defaults to `esnext` | already `"module": "ESNext"` (l.6) | no-op |
| ES5 targeting is a hard error | `"target": "ES2022"` (l.4) | unaffected |
| `downlevelIteration` is a hard error | not set | unaffected |
| `baseUrl` is a hard error | not set — uses `paths` only (l.7-10) | unaffected |
| AMD / UMD / SystemJS are hard errors | none | unaffected |
| Older moduleResolution modes error | `"moduleResolution": "bundler"` (l.15) | unaffected |
| Revised `rootDir` defaults | not set, and `"noEmit": true` (l.18) | negligible |
| **No stable compiler API until 7.1** | **verified: nothing consumes it** | unaffected |
| Vue / MDX / Astro / Svelte / Angular unsupported | none used | unaffected |

The compiler-API point is the one that would normally block a build, so I
verified it rather than assuming: `@tanstack/router-cli`, `router-generator`,
`react-router` and `react-start` declare **no dependency on `typescript`,
`ts-morph`, or any `@ts-*` package**, and no project source imports `typescript`.
The only consumers of `tsc` here are `tsc --noEmit` and the editor. Vite/rolldown
and Babel handle transpilation, so **`typescript` is not on the build path at
all**.

**Benefit, measurable:** typecheck is the slowest local gate the frontend has.
The announcement claims 8-12x; the P0 baseline gives us a clean comparison point.

**Residual risk:** the Go port is a complete reimplementation, so new or
differently-worded type errors are possible even with identical config. This is
cheap to test and trivially reversible — a devDependency that emits no runtime
artifact. Try it, diff `tsc --noEmit` against the P0 clean baseline, revert if
noisy.

---

## 5. The remaining frontend upgrades

**`@types/node` 22.20.1 → 26.1.2 — MECHANICAL.** The runtime is **Node 26.2.0**,
so the types are four majors behind what actually executes. Only `vite.config.ts`
and `server.mjs` touch Node APIs. Expect new type errors rather than runtime
change; that is the point of doing it. Do this *with* the TypeScript upgrade, not
separately — otherwise two sources of new type errors are hard to attribute.

**`srvx` 0.11.22 → 0.12.5 — MECHANICAL.** The documented breaking change is
*"Rename subpath exports to `*Middleware` / `*Plugin`"*. `server.mjs:18` imports
`{ serve }` from the **root** export and uses only `serve({ port, hostname,
fetch })`, so **the rename does not apply to this codebase**. The release notes
also mention Node-adapter corrections to "response handling, header processing,
and body streaming" — not flagged as breaking, but this is the production SSR
entry point, so it needs a real smoke test rather than a green build.

**`@biomejs/biome` 2.4.5 → 2.5.6 — MECHANICAL, sequence it carefully.** A minor
bump can change formatter output and add lint rules. The repo already has 38
files with formatting drift and 3 lint errors (P0-009). Upgrading biome *before*
resolving those makes it impossible to tell new diagnostics from pre-existing
ones. **Fix P0-009 first, then upgrade.**

---

## 6. Maintenance flags

Only one package fails the 12-month test:

- **`num2words` 0.5.14, released 2024-12-17** (~20 months). Used by the voice
  layer to speak numbers as words. Low risk: small, pure-function, stable problem
  domain, no network or parsing surface, and it is at its own latest release.
  **No migration recommended** — flagged for the record, not for action. If it
  ever needs replacing, `Intl.NumberFormat` on the client or a small vendored
  table would cover the EN/ES/FR cases this product needs.

Everything else has shipped within the last 12 months. `arq` (2026-04-16) and
`pgvector` (2026-07-06) are both current.

---

## 7. Ordered upgrade sequence

Every step leaves the tree installable and the suite green. Verify after each:
`tsc --noEmit`, `biome lint`, `vite build`, `pytest -q`, `node --test src/lib/aspire/*.test.ts`.

| # | Step | Class | Rollback |
|---|---|---|---|
| 1 | Pin the eight `"latest"` specifiers to the versions in §2 (P0-006). Delete one of the two lockfiles (P0-007). | — | Revert `package.json`; no code change. |
| 2 | Backend patches together: `langchain-text-splitters` 1.1.2, `uvicorn` 0.52.1, `python-dotenv` 1.2.2. | SAFE | `uv sync` from the previous `uv.lock`. |
| 3 | Frontend patches: `@tanstack/react-start` 1.168.35, `@vitejs/plugin-react` 6.0.5. | SAFE | Restore lockfile. |
| 4 | Fix the 3 lint errors + run `biome format --write` as its own no-behaviour commit (P0-009). | — | Revert commit. |
| 5 | `@biomejs/biome` → 2.5.6. Re-run `biome check`; triage only *new* diagnostics. | MECHANICAL | Revert; step 4 keeps the tree clean either way. |
| 6 | `srvx` → 0.12.5. **Smoke-test SSR against a real request**, not just a build. | MECHANICAL | Single-line revert in `package.json`; `server.mjs` unchanged. |
| 7 | `typescript` → 7.0.2 **and** `@types/node` → 26.1.2 in one commit. Diff `tsc --noEmit` against the P0 clean baseline. | MECHANICAL | Revert both together — devDependencies only, no runtime artifact, no lockfile risk to the app. |
| 8 | `redis` → 8.x | **DEFER** | Blocked by `arq<6`. Re-check when arq widens its pin; then plan `cache.py` retry/timeout policy explicitly (§3). |

Steps 1-3 are risk-free housekeeping and can ship immediately. Steps 4-7 each
want their own commit and their own verification. Step 8 is not schedulable yet.

**No peer-dependency conflicts exist in this sequence.** The only conflict in the
tree is `arq → redis<6`, which step 8 explicitly does not attempt.

---

## 8. What I did not determine

1. **redis-py 6.0 and 7.0 release notes.** I obtained 8.0's breaking changes from
   the GitHub releases page; the 6.0 and 7.0 notes were not on the pages I
   fetched, and the repo's `CHANGES` file stops at 4.0.0. Since the upgrade is
   **blocked regardless** (§3), I did not spend further effort. If arq widens its
   pin, read 6.0 and 7.0 properly before planning — do not assume 8.0's notes are
   the whole story.
2. **Whether `bun.lock` and `package-lock.json` resolve the same tree.** Both
   exist (P0-007). I read installed versions from `node_modules`, which reflects
   whichever manager ran last. Resolving P0-007 should precede any upgrade work.
3. **New APIs worth adopting.** The pack asks for adoption recommendations per
   package. For the TanStack stack, React, Vite, Tailwind and the whole backend,
   **the project is already on the latest release**, so there is nothing newer to
   adopt — the question is answered by the currency table. The one genuine
   adoption question in this codebase is not a version gap at all: it is whether
   to use `@tanstack/ai-client`'s streaming transport that is already installed
   and already wired up but unreachable (P0-001). That decision belongs to P5.
4. **Zod** is on the pack's focus list but **is not a dependency of this project**
   — there is no `zod` in the tree. Validation is Pydantic server-side and
   hand-written TypeScript types client-side. That gap (no runtime validation of
   API responses on the client) is a design observation for P3/P4, not a
   dependency finding.
