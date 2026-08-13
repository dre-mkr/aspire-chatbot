# Agent suites

One scripted conversation per agent, driven through the real site: the `/signup`
wizard is walked, messages are typed into the composer, answers are read off the page.

```bash
npm run e2e -- --preflight
npm run e2e -- --suite all
npm run e2e -- --suite routing_one_chat --headed
npm run e2e -- --suite qa_agent,learn_tutor --run-id my-run
```

Run from `frontend/`. **Start the `frontend` launch config first** (port 3000). The
harness starts the *backend* itself on 8010 and refuses to run if something is
already listening there — it has to own the process to attribute log lines to a
single turn.

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
