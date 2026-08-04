# P4 — TanStack Query audit

Diagnosis only. No code changed.

---

## 1. Query keys — a real factory, with two leaks

`queries.ts:33-66` is a proper domain-shaped, hierarchical key factory with a
docstring that states the rule it exists to enforce:

> *"Keys are declared here rather than inline at the call sites so that
> invalidation cannot silently miss one. A key written twice is a key that will
> eventually be written differently."*

Complete inventory:

| Key | Shape | Owner in key? |
|---|---|---|
| `conversations(ownerId)` | `["conversations", ownerId]` | ✅ |
| `allConversations()` | `["conversations"]` | n/a (prefix) |
| `conversation(ownerId, threadId)` | `["conversations", ownerId, threadId]` | ✅ |
| `messages(ownerId, threadId)` | `["conversations", ownerId, threadId, "messages"]` | ✅ |
| `gameState(threadId)` | `["games", "state", threadId]` | ❌ **P4-008** |
| `eligibilityState(threadId)` | `["eligibility", "state", threadId]` | ❌ **P4-008** |

**No collisions.** The hierarchy is deliberate and correct — `messages` sits under
`conversation` so a single invalidation reaches both.

**Leak 1 (P4-005).** The `["games"]` and `["eligibility"]` namespaces are written
as inline string literals in **three separate files** — `AccountControl.tsx:99-100`,
`signin.tsx:65-66`, `signup.tsx:166-167` — bypassing the factory entirely. This is
precisely the failure the factory's docstring warns about, already happened, three
times. Renaming either namespace breaks all three silently.

**Leak 2 (P4-008).** `gameState` and `eligibilityState` omit `ownerId`, while the
conversation keys include it with a strong comment explaining that owner-in-key is
*"the whole defence against showing one person's conversations to the next"* and
that *"clearing caches at sign-out works only as long as somebody remembers to."*
For games and eligibility, the codebase relies on exactly that — somebody
remembering, in three places. They did remember. The inconsistency is the finding:
two different defences for the same class of problem, one structural and one
manual.

### Language and persona in keys

- **Persona:** not in any key — and correctly so, because persona is never set
  (P3-005). If a picker is ever wired, `gameState` and the conversation keys will
  need it. **Record this as a precondition of building that feature.**
- **Language:** `eligibilityStateQuery` takes `language`, uses it in `queryFn`,
  and **omits it from the key**. Already filed as **P1-003**; P4 confirms the
  mechanism precisely. The comment argues the omission is deliberate ("the flow
  opened in a language and finishes in it") — but `invalidateAfterTurn:312`
  invalidates that exact key on **every settled turn**, forcing a refetch that
  re-runs `queryFn` with whatever `voice.language` is *now*. The intent is real;
  the implementation does the opposite.

---

## 2. Colocation and duplication — clean

All five query functions live in `queries.ts` as typed `queryOptions` objects and
are consumed by importing them. No inline `useQuery({queryKey, queryFn})` anywhere.
**No duplicated fetch logic** — each domain has exactly one fetcher
(`fetchConversations`, `fetchConversation`, `fetchGameState`,
`fetchEligibilityState`), each imported once.

This part of the reference intent is fully met.

---

## 3. `staleTime` / `gcTime`

`staleTime` is set deliberately per query, with reasoning, in every case:

| Query | staleTime | Correct? |
|---|---|---|
| `conversationsQuery` | `30_000` + refetch on focus | ✅ Right. A conversation continued in another tab should appear; the list is cheap. |
| `conversationQuery` | `Infinity`, focus off | ✅ Right. A settled transcript does not change behind you. |
| `gameStateQuery` | `Infinity`, all refetches off | ✅ Right, and well argued: alt-tabbing during a word scramble must not re-read the session. |
| `eligibilityStateQuery` | `Infinity`, all refetches off | ✅ Right, same reasoning. |

**`gcTime` is never set anywhere (P4-003).** It therefore defaults to 5 minutes,
which quietly defeats two stated intentions:

- `conversationQuery`'s docstring says it is *"Kept for the session once loaded."*
  It is not. The query is **never mounted** (see §6), so it has no observers, so
  it is garbage-collected 5 minutes after each imperative read. Flip between two
  chats with a 5-minute gap and both refetch.
- `gameStateQuery`'s `staleTime: Infinity` protects a child mid-puzzle from a
  refetch — but if the card is unmounted for 5 minutes the entry is evicted and
  the next read refetches anyway.

Same class as P0-004: a docstring describing behaviour the code does not deliver.

**On the brief's premise:** the pack says *"the 338-row knowledge base and the
persona config are near-static… treating them the same is a finding."* There is
**no knowledge-base query and no persona-config query on the client** — both live
entirely server-side. That comparison does not apply here.

---

## 4. Invalidation

**No broad `invalidateQueries()` with no key exists anywhere.** Every call is
keyed. That is better than most codebases.

But `invalidateAfterTurn` (`queries.ts:306-319`) has an over-broad line (P4-004):

```ts
void queryClient.invalidateQueries({ queryKey: keys.conversation(owner(), threadId) }); // l.317
void queryClient.invalidateQueries({ queryKey: keys.conversations(owner()) });          // l.318
```

Line 318's key `["conversations", owner]` is a **prefix of every transcript key
for that owner**, so it invalidates not just the rail's list but **every cached
conversation transcript**. That makes line 317 entirely redundant, and it defeats
`conversationQuery`'s `staleTime: Infinity` for every *other* conversation on
every settled turn.

The intent (line 315-316 comment) is that 317 reaches this conversation's
transcript via prefix matching — correct. Line 318 was meant to refresh only the
list ordering. It needs `exact: true`, or the list needs a key that is not a
prefix of the transcripts.

**Writes that invalidate nothing:** none found. Every write path either
invalidates or optimistically sets.

---

## 5. Mutations — there are none (P4-002)

**Zero `useMutation` in the codebase.** Every write is a hand-rolled
`setQueryData` followed by a fire-and-forget `fetch`.

The optimistic updates themselves are *good*, and one detail is genuinely subtle
and correctly handled: `upsertConversation:220` and `retitleInCache:266` both call
`cancelQueries(..., { revert: false })` **before** writing, because a list fetch
started on mount can otherwise land afterwards and erase the row. That is a real
race, correctly identified and closed.

What is missing is the other half of an optimistic mutation:

- **No rollback.** `nameConversation` (`use-conversation.ts:447-460`) writes the
  title to cache, then `void renameConversation(...).catch(() => undefined)`. On
  failure nothing is reverted and nothing is invalidated, so the UI shows a title
  the server does not have — **indefinitely**, until some unrelated invalidation
  happens to refetch the list.
- **No `onSettled` reconciliation.** Success invalidates; failure does not.
- **No error surface.** A failed rename is indistinguishable from a successful one.

I could not simulate the failure path as the pack asks, because there is no
mutation object to force into an error state — the failure handling is a bare
`.catch(() => undefined)`. That is itself the finding.

**Which writes would benefit from a real mutation:** rename, regenerate-title, and
delete. **Message send would not** — it is deliberately outside Query
(`queries.ts:4-8`: *"Query owns durable server state. It does not own the in-flight
assistant response."*). That boundary is correct and should be preserved.

---

## 6. State coverage — **the worst finding in this pass (P4-001)**

I grepped every `.ts`/`.tsx` file for `isPending`, `isLoading`, `isError`,
`isFetching`, `isSuccess`, `isPlaceholderData`, `.error`, and `status ===`.

**Not one component reads a single TanStack Query status flag.** The only matches
were HTTP status codes in `api.ts` and `conversations.ts`.

All three `useQuery` call sites read `.data` and nothing else:

| Call site | What it reads |
|---|---|
| `use-conversation.ts:307` | `conversations.data ?? []` |
| `AspireChat.tsx:254` | `if (gameQuery.data) setGame(...)` |
| `AspireChat.tsx:277` | `eligibilityQuery.data` |

And `Rail.tsx:132` renders a single branch: `history.length === 0 ? <p className="rail__empty">`.

So **loading, error, empty, background-refetching and stale-while-revalidate all
render identically** — as the empty state. Not "a spinner for all five": the same
*empty* state for all five. A child whose connection dropped is told they have no
conversations.

**In fairness, half of this is argued.** `conversationsQuery:83-86` says: *"History
that fails to load must never be an error in the reader's face. The rail simply
shows what it has."* Collapsing **error → empty** for a sidebar is a defensible
product call, and I am not going to call it a bug.

What is **not** argued, and is a genuine gap:

- **loading → empty.** On a slow connection the rail asserts "no conversations"
  and then pops them in. That is a false statement rendered with confidence, which
  is worse than a skeleton.
- **No recovery.** Because failure is invisible, there is no retry affordance. The
  rail is wrong until something else happens to refetch it.
- Game and eligibility (`retry: false`, `.data` only) silently render no card on
  failure — defensible, since the code argues games are additive.

---

## 7. Global client state — nothing to migrate

**Zustand is not a dependency.** `@tanstack/react-store` and `@tanstack/store`
*are* in `package.json`, but grep finds **zero imports** of either (P4-009).

So the reference intent's "server data kept out of global client state" is
satisfied trivially: there is no global store. Server state lives in Query,
conversation state lives in `use-conversation`, and the boundary between them is a
single documented function. **Nothing to migrate.**

---

## 8. SSR — wired correctly, and inert

`router.tsx:17` calls `setupRouterSsrQueryIntegration({ router, queryClient })`,
which is right. But every user-scoped query is gated on
`enabled: Boolean(currentSession())`, and `currentSession()` returns `null` on the
server (`session.ts:104`).

So **no query ever runs during SSR, and nothing is ever dehydrated.** The
integration is correct and has nothing to do.

This answers the pack's question directly: no query refetches on mount despite
having SSR data, because **no query has SSR data**. Not a bug — but it means the
document ships with an empty rail and an empty transcript regardless, and the
first meaningful paint of user content always waits for a client-side round trip
after the anonymous-session handshake.

---

## 9. Re-render cost (P4-006) — structural claim, not measured

`use-conversation.ts:307` subscribes to the **entire conversations list** inside
the hook that owns the whole chat surface. Its consumer is `AspireChat`, which
renders `Transcript`, which has no virtualization (P0-005).

Consequence: every write to `["conversations", owner]` — the optimistic insert on
send, the retitle, and the post-turn invalidation refetch — re-renders the full
message list. `groupByRecency` is correctly memoized on `conversations.data`
(l.308-311), but that memo protects the grouping computation, not the render.

The fix is not `select` — the whole list is used. It is **moving the subscription
into `Rail`**, which is the only component that needs it.

**I have not profiled this.** The pack asks for a profiler trace of the composer
and message list during a stream; that needs the app running, which is still
blocked on the P0 gap. This is a claim from the component graph, and it should be
measured in P5 before anyone acts on it.

---

## 10. Retry policy

Every query overrides the default: `conversationsQuery` and `conversationQuery`
use `retry: 1`; `gameStateQuery` and `eligibilityStateQuery` use `retry: false`.
`root-provider.tsx:4` constructs `new QueryClient()` with **no `defaultOptions`**,
so anything added later silently inherits TanStack's default of **3 retries with
backoff** — a trap for the next query someone adds (P4-007).

**Are 4xx retried?** Yes. `retry: 1` is unconditional, so a 401 from an expired
session and a 404 for a deleted conversation both get retried once. It should be
status-aware.

**Do retries multiply LLM cost?** **No — and this is worth stating plainly.**
Every model-spending call (`/chat`, `/api/title`) is a bare `fetch` outside Query
entirely. Query never touches an endpoint that costs money. The pack's concern
does not apply here.

---

## 11. Summary

**9 findings: 0 × S0, 0 × S1, 6 × S2, 3 × S3.**

**Worst: P4-001** — no component reads any query status flag, so loading, error,
empty and refetching all render as the empty state. Half of that is a defended
product decision; the loading→empty half is not, and it means the rail confidently
tells a child they have no conversations while it is still fetching.

**Most likely to bite later: P4-005** — the `["games"]`/`["eligibility"]` keys are
inlined in three files, which is exactly the failure the key factory's docstring
warns about, already realised.

This is the strongest area of the codebase so far. The key factory is real and
hierarchical, query functions are colocated with typed options, stale times are
individually reasoned, there is no unkeyed invalidation, there is no global store
to untangle, and the optimistic-write race with in-flight list fetches was spotted
and closed correctly. The findings are mostly about the *other* half of the
patterns being missing — mutations without rollback, optimism without error
surfaces, `staleTime` without `gcTime` — rather than about anything being wrong.
