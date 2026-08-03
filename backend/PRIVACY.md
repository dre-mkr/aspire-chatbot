# What ASPIRE stores, and for how long

This product is used by children. That is the reason for every decision below,
and the reason several of them are more restrictive than they strictly need to
be.

## Identities

There are two kinds, in one table, distinguished by `account_type`.

**Anonymous.** Created the first time a browser asks for a session. It holds a
`device_id` — an opaque value the client minted for itself — and a **keyed hash**
of the IP the session was created from. Neither is a name, and neither is used
to sign in.

The device id is a *seed*, never a credential. `POST /api/auth/anonymous` always
creates a new row, even when the caller presents a device id that already
exists, because looking it up and returning that identity's session would mean
"hand me a device id and I will hand you their conversations". Authorisation is
a signed token and only a signed token.

**Registered.** Adds an email, a password hash, a name, and — because the
sign-up flow asks for them — date of birth, island, school, and, for an account
covering a child under 13, the name, email and phone number of the adult who
holds it.

## Why an under-13 account looks like that

Date of birth is asked in step 1, before any credentials, because it decides
what happens next. Under 13, the account belongs to the adult named during
sign-up: their email and password are the ones on it. The child's details sit on
the same row.

This is a deliberate departure from the posture the eligibility flow holds,
where a minor's answers never leave the device and the model's narration is
dropped server-side before it can cross the wire. It was asked for explicitly.
It should be reviewed by somebody who knows the applicable rules — COPPA and
GDPR Article 8 both bear on storing a child's birth date and school alongside a
guardian's contact details — rather than treated as settled because it is
implemented.

## Retention

| What | Kept for |
| --- | --- |
| Anonymous conversations, unclaimed | `ANONYMOUS_RETENTION_DAYS`, default **180 days** |
| Anonymous conversations, claimed into an account | As long as the account |
| Registered accounts and their conversations | Until the account is deleted |
| One-time links (reset, verify, sign-in) | 15 minutes to 24 hours, then unusable |
| Eligibility answers and verdicts | Never stored server-side — device only |

The window runs from when a conversation was **last touched**, not from when the
identity was created. Somebody who has used the same browser for a year without
signing up does not lose the chat they were reading yesterday.

`app/retention.py` enforces this nightly at 03:15, off the request path. It
deletes only anonymous identities that have never been claimed and have no
recent conversation; messages go with the conversation and conversations with
the identity, by `ON DELETE CASCADE`. It is safe to run twice and logs counts
only — which identities, and anything they asked, is precisely what the job
exists to stop keeping.

## Anonymous abuse controls

Anonymous access removes the usual lever: there is no address to ban. So the
limit is the lever.

- Anonymous sessions are capped per IP per hour
  (`ANONYMOUS_SESSIONS_PER_IP_PER_HOUR`, default 30), counted in Valkey.
- The cap **fails open**. A cache outage must not stop a child opening the app;
  the cost of missing some scripted abuse for an hour is far below the cost of
  refusing everybody.
- Session creation logs the new identity, a truncated keyed IP hash, and a
  truncated device id. No address, no user agent, no content.

## What is deliberately not collected

No IP addresses in the database — only keyed hashes, which are enough to see
that one source opened four hundred sessions and useless for finding where a
child lives. No user agents. No analytics identifiers. No content in any email:
a reset message is proof of control over an address and nothing more, and every
extra fact in it is a fact that leaks if the mailbox is shared — which, for this
audience, is the normal case rather than the exception.
