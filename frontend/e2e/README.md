# Agent suites

One scripted conversation per agent, driven through the real site: the `/signup`
wizard is walked, messages are typed into the composer, answers are read off the page.

```bash
npm run e2e -- --preflight
npm run e2e -- --suite all
npm run e2e -- --suite routing_one_chat --headed
npm run e2e -- --suite qa_agent,learn_tutor --run-id my-run
npm run e2e -- --suite judging --against https://aspire.eccugenai.app
```

Run from `frontend/`. **Start the `frontend-e2e` launch config first** (port 3001,
`VITE_ASPIRE_API_URL=http://localhost:8010`) and pass `--web http://localhost:3001`.
The harness starts the *backend* itself on 8010 and refuses to run if something is
already listening there — it has to own the process to attribute log lines to a
single turn.

**The `frontend` config on port 3000 is the wrong one to pair with a run.** Its API
base is whatever it was started with, and `src/lib/config.ts` falls back to
`http://localhost:8000` when `VITE_ASPIRE_API_URL` is unset — so the harness
spawns a backend, the site talks to a different one, and the results describe a
service nobody is testing. `checkWiring` in `run.mjs` reads the browser's own
resource timings after the first page load and aborts if the two disagree. It
exists because that is exactly what happened the first time the judging suite ran:
green preflight, empty log slice, and an answer served from another box's cache.

## Against a deployment

`--against <origin>` takes the site and the API from a deployed host and starts
nothing. There is no log to slice, so `log`, `noLog`, `route` and `noRoute`
expectations — and the wire/log agreement check — are recorded as **skipped**
rather than passed, and the summary counts them in their own column. Two sources
instead of three, which is what a judge gets.

Readiness is a `GET` on a `POST`-only route: nginx proxies only `/api/` and `/v2/`
to the backend, so `/health` and `/ready` fall through to the SPA and answer 404
with HTML. `GET /v2/session` returning JSON is the cheapest proof the API is up
and routed.

A deployed run writes real rows: an anonymous account, real conversations, real
model spend, and the complaint case can raise a real escalation ticket. Warn
whoever watches ASPIRE support before running it.

## The judging suites

The 14 cases the client said they would test, split by identity because a suite
runs as one reader:

| Suite | Identity | Cases |
|---|---|---|
| `judging` | A (signed out) | 1–12 |
| `judging_memory` | A | 14 — two facts planted, both recalled |
| `judging_persona_{stella,orion,aurora}` | B, D, E | 13 — the same three questions each |

Case 13's real assertion is across suites, so it is made afterwards:

```bash
node e2e/judging-compare.mjs <runId>
```

It fails if two personas answer a question more than 80% alike, or if Stella
runs longer than Aurora.

These are written against what must be true on 20 Aug, not against today, so a
red is the work list rather than a broken test.

## What a turn is judged against

Three independent sources, because any one of them can lie:

| Source | Answers |
|---|---|
| the wire | *which* agent answered — `usage.agent` from the `done` event |
| the DOM | what the reader actually saw |
| the backend log slice | *why* it went there — confidence, stickiness, which node claimed it |

The app discards `usage` (`src/lib/aspire/stream.ts`), so `lib/browser.mjs` tees a
clone of every `/v2` response into `window.__aspire_turns`. A disagreement between
the wire and the log is itself a failure.

## Writing a suite

`scripts/<name>.mjs` exports `suite` (name, identity, description) and
`steps(ctx)`. A step is `{ say }`, `{ act }` (click something that starts a turn),
`{ custom }`, or `{ domOnly }` (no graph turn at all — an eligibility answer).

```js
{ say: "Which papers must a family bring to a branch?",
  expect: { agent: "qa_agent", route: true, citations: true } }
```

`expect` keys: `agent` (string or list), `mustMatch` / `mustNotMatch`, `directive` /
`noDirective`, `chips`, `surface`, `citations`, `log` / `noLog` (regexes against this
turn's log slice), `route` / `noRoute`, `allowEmpty`. Mark a step `critical: true`
when everything after it becomes uninterpretable if it fails.

**`noRoute` is a real assertion, not a gap.** The continuation bypass and the
single-option shortcut both return before the router logs, so the *absence* of a
route line is how a card turn or a widget continuation is detected.

## Identities

Six, in `lib/identities.mjs`. Date of birth is the whole game: it sets the age band,
the band picks the persona, and the pair decides which agents are reachable at all.
Every DOB sits well clear of a band boundary. **F (nova/educator) is the control** —
one routable agent, so the router short-circuits with no model call. If F fails, the
fault is the harness.

Emails are unique per run, so a re-run never collides with an existing account.

## Preflight

`--preflight` refuses to run the suites when concepts have no embeddings, when the
classifier silently fell back to `CHAT_MODEL`, when an agent module failed to import,
or when there is no checkpointer. Each of those makes the suites measure a different
system while still passing their first assertion.

## Artifacts

`artifacts/<run-id>/` (gitignored): `transcript.md` and `turns.json` per suite,
`diagnosis.md` for the routing run, `backend.log`, and screenshots on failure.
