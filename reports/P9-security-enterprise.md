# P9 — Security, privacy, and enterprise readiness

Diagnosis only. No code changed.

## ⚠ Headline: **no S0 found.** Nothing to surface immediately.

The three S0 candidates were tested directly rather than reasoned about, and all
three came back clean. Details in §1-§3.

---

## 1. Secrets — clean

**Full git history, every commit, every file:**

```
git rev-list --all | xargs -n1 git grep -IE 'sk-…|sk_live_…|xoxb-…|AIza…|ghp_…|
    postgres://user:pass@|rediss?://user:pass@|-----BEGIN … PRIVATE KEY'
```

Every hit is a **placeholder**: `postgresql://user:password@ep-example-123456-pooler…`
in `backend/.env.example`, and `u:p@host`, `user:pw@valkey.example.com` in
`tests/test_db_engine.py` / `test_cache_keys.py`. **No real credential has ever
been committed.**

**Built client bundle** (re-verified from P3): no `sk-`, no JWT-shaped strings, no
connection strings, no `*_API_KEY`, no server module names. The frontend has no
server functions and no provider SDKs, so there is structurally nothing to leak.

`.env` is git-ignored in both `backend/` and `frontend/`, and every secret is read
through `pydantic-settings` from the environment. Confirmed.

---

## 2. Auth and IDOR — the design is sound, and it is tested

The device-ID-seeded model is implemented exactly as its docstring claims:

> *"A device id seeds the creation of an anonymous identity. It is never accepted
> as proof of one."*

`POST /api/auth/anonymous` always **creates a new row**, never looks one up, so
presenting someone else's device id buys nothing. Authorization is a signed JWT
and only a signed JWT.

| Property | Finding |
|---|---|
| Algorithm | HS256, explicit `algorithms=[ALGORITHM]` on decode — no `alg:none` confusion |
| Key | `SESSION_SECRET`, **no default** — `_secret()` raises rather than falling back (`auth.py:78-87`) |
| Expiry | 30 days, `exp` in `options={"require": [...]}` so it cannot be omitted |
| Revocation | `session_epoch` claim — bumping it invalidates every issued token without a denylist |
| Grace | 10 minutes, chat endpoints only; read endpoints get none |
| Replay | `jti` present but **not tracked** — see below |
| Failure mode | every failure returns `None` identically, so probing cannot distinguish expired from forged |

**IDOR tested directly.** `tests/test_auth_idor.py` runs against the real
database — 7 tests, **all passing in 105s** (they execute, they do not skip):

- a device header alone authorises nothing
- a device id cannot be exchanged for its owner's session
- one identity cannot read another's conversation
- one identity cannot rename another's conversation
- unsigned and tampered tokens are refused
- a valid token reads only its own conversations
- chat still works with no identity at all

And the repository layer backs it structurally: `load_transcript` puts ownership
**in the WHERE clause**, so "not yours" and "does not exist" are the same answer.

**Residual (P9-005, S3):** `jti` is minted but never recorded, so a stolen token
is replayable until expiry or an epoch bump. For a 30-day token that is a long
window. Standard for stateless JWT, worth an explicit decision rather than a
default.

---

## 3. XSS through model output — tested, clean

12 payloads through the live renderer (`parseInline` / `safeHref`):

| Payload | Result |
|---|---|
| `<img src=x onerror="alert(1)">` | no link, renders as text |
| `<script>alert(document.cookie)</script>` | no link |
| `[click me](javascript:alert(1))` | **href rejected → plain text** |
| `[click me](JaVaScRiPt:alert(1))` | rejected (case-insensitive) |
| `[x](  javascript:alert(1)  )` | rejected (whitespace-padded) |
| `[x](java\0script:alert(1))` | rejected (null-byte) |
| `[click](vbscript:msgbox(1))` | rejected |
| `[x](data:text/html,<script>…)` | rejected |
| `[a](//evil.com)` | rejected (protocol-relative) |
| `**<svg onload=alert(1)>**` | no link |

`safeHref` is a proper **allowlist** — `https?:`, `mailto:`, bare email, bare
domain — everything else returns `null` and renders as literal text. Combined with
**zero `dangerouslySetInnerHTML` anywhere** and React's text escaping, model output
cannot execute. **No dangerous href produced.**

One quality artefact (P9-006, S3): the autolinker matched `document.co` inside
`<script>alert(document.cookie)</script>` and turned it into a link, because
`.co` is in its TLD list. Harmless — the href is `https://document.co` — but it
means ordinary prose containing a dotted word (`config.io`, `index.js`) can become
a spurious link.

---

## 4. Authorization surface

| Route | Auth | Justified? |
|---|---|---|
| `POST /chat`, `/chat/stream` | optional principal | ✅ Anonymous questioning is the product |
| `POST /api/title` | **none at all** | ❌ **P1-001** — no auth, no limit, one model call |
| `GET /api/conversations*` | `require_principal` | ✅ |
| `PATCH/DELETE /api/conversations/{id}` | `require_principal` + owner in WHERE | ✅ |
| `POST /api/auth/anonymous` | none, by design | ✅ but see rate limit below |
| `/api/voice/*` | none + own limiter | ⚠ metered but unauthenticated |
| `/games/*`, `/eligibility/*` | none (thread-scoped) | ⚠ server-side session keyed by thread id |
| `/health` | none, **not exposed by nginx** | ✅ loopback only |

**Rate limiting (P1-001, already S1):** only two limiters exist — anonymous
session creation (`sessions.py:125`) and voice (`voice/limiter.py`). **Message
send, `/api/title`, and embedding have none.** The session limiter also
**fails open** when Valkey is unreachable (P1-010).

**Input validation** is solid: Pydantic `max_length` on every string field, SQL
exclusively through SQLAlchemy parameter binding (no string interpolation
anywhere), `encodeURIComponent` on path params client-side, no `shell=True`, no
`eval`, no template rendering of user input. **No injection surface found.**

---

## 5. Headers and TLS — the largest security gap

`frontend/src/middleware.ts` sets three headers on the **SSR document only**:
`X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
`X-Frame-Options: DENY`.

**Missing entirely (P9-001, S2):**

| Header | Status |
|---|---|
| **Content-Security-Policy** | **absent** — no CSP at all, no `frame-ancestors` |
| **Strict-Transport-Security** | **absent** — certbot does not add HSTS |
| Permissions-Policy | absent |
| `nosniff` on static assets | **absent** — nginx serves `/assets/` directly and adds only `Cache-Control`, so the middleware's headers never apply to JS or CSS |

For a product whose core function is rendering language-model output, CSP is the
defence-in-depth layer that catches whatever `safeHref` misses. §3 shows the
sanitiser currently holds — CSP is what keeps that true after a future edit.

**TLS (P9-002, S3):** the committed nginx config has the certificate lines
**commented out** and relies on certbot to rewrite the `:80` block into a
redirect. As committed it serves plain HTTP on `:80` with no redirect. That is a
documented bootstrap sequence rather than a bug, but it means the repo config is
not TLS-safe on its own, and **no HSTS is added at any point**.

**CORS:** `["*"]` with `allow_credentials=False` (P0-008). nginx makes the app
same-origin in production so browsers never preflight, but the API remains
reachable cross-origin for unauthenticated abuse.

---

## 6. Privacy — children's data

### Data inventory

| Field | Where | Why | Retention |
|---|---|---|---|
| `users.device_id` | Postgres | abuse investigation only; never a lookup key | 180d (anonymous) |
| `users.created_ip_hash` | Postgres | **HMAC-SHA256 of IP**, not the IP | 180d |
| `users.email`, `display_name` | Postgres | registered accounts | indefinite |
| `users.date_of_birth`, `is_minor` | Postgres | age gating | indefinite |
| `users.island`, `school` | Postgres | programme context | indefinite |
| `users.guardian_name/email/phone` | Postgres | minor consent | indefinite |
| `conversations.*` + `messages.content` | Postgres | transcript | 180d (anonymous) |
| `eligibility_outcomes` | Postgres | **anonymised verdict counts only** | indefinite |
| answers to the eligibility flow | **device only** | never leave the browser | n/a |

**Two design decisions here are genuinely good and should be preserved:**

1. **IP addresses are never stored** — only `hash_ip()`, an HMAC keyed with the
   signing secret so it cannot be reversed against the small IPv4 space.
2. **The eligibility flow is routed around the model entirely** (`main.py:143-149`).
   A minor's age band, citizenship, parish and school answers never enter a
   prompt, a checkpointer, or a summary job; the transcript records only
   *"[Opened the ASPIRE eligibility check … I cannot see the answers or the
   outcome]"*. The durable result lives on the device. That is real data
   minimisation, deliberately built.

### PII in logs — one real problem

I grepped every `logger.*` call rather than trusting the config.

**Clean:** no question, answer, or message content is ever logged — only lengths
(`len(reply)`), thread ids, and languages. IPs are hashed at
`sessions.py:126,152`.

**P9-003 (S2) — `mail.py:100-105` logs full email bodies:**

```python
if not api_key:
    logger.info("[mail:console] to=%s subject=%s\n%s",
                message.to, message.subject, message.text)
```

This is the **default path** whenever `RESEND_API_KEY` is unset. `message.text`
contains the **sign-in and password-reset magic links** — working authentication
tokens — alongside the recipient's email address. The comment says this is
deliberate for local development, and for local development it is right. The
problem is the failure direction: a production deploy that forgets the mail key
**silently starts writing credentials and email addresses to the system journal**
rather than failing.

**P9-004 (S3):** `sessions.py:152` logs `device=%s` unhashed. Device ids are not
secrets and are not accepted as auth, but they are stable per-browser identifiers
for children, logged in plaintext where the IP beside them is hashed. Inconsistent.

### Deletion — the path exists and does not run

`retention.py` deletes expired anonymous identities and cascades to their
conversations and messages. **P7-001 established it has never run** — 20
identities are ~8 months past the published 180-day commitment.

Three further gaps in deletion coverage:

- **The response cache is not reached.** A cached answer keyed by question hash
  survives deletion for up to 6h (bounded by TTL, so it expires — but it is not
  *deleted*).
- **The vector store is not reached** — correctly, because it holds only KB
  content, no user data. Worth stating so nobody "fixes" it.
- **Backups are not reached.** Nothing documents backup deletion, because nothing
  documents backups at all (§7).

### Third parties

| Recipient | What | Disclosed? |
|---|---|---|
| **OpenAI** | every question + retrieved KB context + conversation history | **needs confirmation** |
| **ElevenLabs** | text to synthesise, audio to transcribe | **needs confirmation** |
| **Neon** | all persisted data | infrastructure |
| **Google Fonts** | IP, user-agent, referer of **every child** on page load | **P3-003 — likely undisclosed** |

**I could not verify provider training/retention settings** — that requires
console access to the OpenAI and ElevenLabs organisations. OpenAI's API default is
no-training with 30-day abuse retention, but *defaults are not a control*: this
needs the actual org setting screenshotted for the file.

### Questions for the programme's data-protection owner

I am not making legal determinations. These are the questions:

1. Is transmitting children's free-text questions to OpenAI (US) covered by the
   programme's privacy notice and any data-transfer basis SKN requires?
2. Same for ElevenLabs — **voice recordings of children** are biometric-adjacent
   in several regimes.
3. Is the Google Fonts request from every child's browser disclosed? (Removable
   entirely — P6-003.)
4. Is 180 days the agreed retention for an anonymous child's transcript, and what
   is the basis? (It is currently **not enforced** — P7-001.)
5. Registered minors' `guardian_name/email/phone`, `school`, `island` and
   `date_of_birth` have **no retention limit at all**. What is the intended one?
6. What is the parental access/erasure route, and who fulfils it? No admin
   surface exists.
7. `users.device_id` is retained for "abuse investigation" — is that a documented,
   agreed purpose?
8. 2,473 anonymous user rows exist for visits that **never asked a question**
   (P7). Is creating a record for a mere visit proportionate?

---

## 7. Operational readiness — the weakest area in the entire audit

| Capability | Status |
|---|---|
| Structured logging | stdlib `logging`, `%s` formatting, plain text — not JSON |
| **Correlation IDs** | **none.** Grep found only a code comment. No request→LLM→response tracing |
| **Metrics** | **none.** No prometheus, opentelemetry, statsd |
| **Error reporting** | **none.** No Sentry or equivalent |
| Observable in production | **only** the cache hit rate on `/health` (and P7-006: it is lifetime-cumulative) |
| p50/p95/p99 latency | **not observable** |
| Token spend | **not observable** (`log_prompt_cost` exists but the memory window is off) |
| Error rate | **not observable** |
| **Alerting** | **none.** Nothing pages anyone. No runbook |
| **Backups** | **none documented.** `deploy/README.md:381` mentions backing up `backend/.env`. No DB schedule, no tested restore, **no RPO/RTO** |

**CI gates (P9-007, S1).** `.github/workflows/deploy.yml` has exactly **one
step**: SSH to the VPS and run `update.sh`. Every push to `main` deploys to
production with:

- ❌ no typecheck ❌ no lint ❌ no tests ❌ no build verification
- ❌ no bundle budget ❌ no security scan ❌ no eval gate

487 backend tests and a clean `tsc` exist and **nothing runs them before
production**. The eval workflow added in P8 is currently the only automated
quality gate in the repository.

**Deployment.** Ordering is correct: `alembic upgrade head` (line 83) runs
**before** the asset swap (113-114) and the restart (120). The frontend swap is
atomic via symlink rename. Rollback is documented — re-run `update.sh` with a
commit ref (line 41) — though migrations are forward-only in that path.

**Not zero-downtime:** `systemctl restart aspire-api aspire-web` is a hard
restart. Worse, restarting `aspire-api` **discards every active conversation's
memory**, because the checkpointer is in-process (P0-003). A mid-afternoon deploy
silently resets every conversation in flight.

### Load test — **not run**

I did not run k6 or Locust, and I will not report a breaking point I did not
measure. Doing it honestly means sustained concurrent conversations against the
real agent, and every one of those is billable OpenAI traffic — that needs your
explicit go-ahead and a spend ceiling.

What I can say from measured facts, as a hypothesis to test rather than a result:
the first resource to exhaust is most likely the **default asyncio threadpool**,
because retrieval is synchronous and runs there via `run_in_executor` (P1
verified) at ~316ms p50 per call (P8 measured). Behind it sit the 10-connection DB
pool, `--workers 1`, and unbounded `InMemorySaver` growth. **All hypotheses.**

To run it properly I need: a spend ceiling, confirmation of the target
environment, and ideally a stub provider so the test measures *our* limits rather
than OpenAI's.

---

## 8. Summary

**7 findings: 0 × S0, 1 × S1, 3 × S2, 3 × S3.**

**No S0.** The three candidates — committed secrets, IDOR, XSS through model
output — were each tested directly and each came back clean. The auth design is
genuinely well built, the IDOR defence is structural *and* covered by 7 passing
tests against a real database, and `safeHref` rejected all 12 XSS payloads.

**Worst — P9-007 (S1):** there are no CI gates at all. Every push to `main`
deploys to a government production system serving children with no typecheck, no
lint, no tests, and no build verification, despite 487 tests existing.

The security posture is better than the operational posture by a wide margin.
Someone thought carefully about IDOR, hashed IPs, kept a minor's eligibility
answers off the model entirely, and wrote an allowlist rather than a denylist for
hrefs. Nobody has yet made the system observable, alertable, backed up, or gated.

**What I could not verify:** provider training/retention settings (needs console
access), and the load test (needs authorisation to spend).
