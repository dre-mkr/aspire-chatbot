# Client checklist — status with evidence

2026-08-14 · branch `fix/judging-readiness` · baseline tag `pre-judging-fixes` (`2c8e529`)

**No status here says DONE without something that can be re-run behind it.** The
evidence column names a judging case, a test, or a measurement. "Judging N" means
case N of `frontend/e2e/scripts/judging.mjs`, which runs a real browser against
the real site, signed out.

The judging suite is **13 of 13**, from 8 of 12 when this work started.

---

## The five things the client said they would personally test

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Escalation offers real contact details | **DONE** | Judging 11. `aspire@gov.kn`, `+1 (869) 667-5566`, `aspire.gov.kn`, from config, in every adult decline and in the prompt. `tests/escalation/test_decline.py::TestTheContactDetails` |
| 2 | Orion persona works | **PARTLY** | The mid-thread switch is fixed and was a frontend cache, not backend gating (`lib/stream/session.ts`). Orion answers correctly for a signed-in 13-18 account: `judging_persona_orion`, 3/3. **The "assistant could not be reached" error is still unattributed** — leading hypothesis is an un-retried transient, now retried (T3.3), but not reproduced and so not proven |
| 3 | Factual questions are not hijacked into forms | **DONE** | Judging 2, the QA report's own failing case. Twelve rule-and-process phrasings moved off the card path. Corroborated independently: the latency probe went from 25 to 29 of 30 golden questions producing a visible answer |
| 4 | Spanish and French with no English bleed | **DONE** | Judging 9 (ES), judging 10 (FR). A reply-language rule now exists in the prompt at all; the decline follows what the reader WROTE, not the session token |
| 5 | Short-first answers with next-step chips | **PARTLY** | Answers are short: measured across 22 turns and four bands, every answer is well under its cap (5-8: 39 median against 120) and the length gate never fires. Chips appear on 8 of 13 answers; **Spanish and French answers carry none**, which is an open decision |

---

## Safety

| Item | Status | Evidence |
|---|---|---|
| No banned word can reach a rendered answer | **DONE** | Judging 7. Every outbound gate now runs before delivery, not after. `tests/graph/test_stream.py::TestTheReaderGetsTheCorrectedAnswer` |
| No PII can reach a rendered answer | **DONE** | Same mechanism; `test_a_phone_number_is_redacted_before_it_is_sent` |
| Links stripped for under-16s | **DONE** | `test_a_link_is_stripped_before_it_is_sent` |
| Stored transcript equals delivered text | **DONE** | `test_what_is_stored_is_what_was_sent`. These disagreed before: Postgres kept the uncorrected version |
| Distress is heard in all three languages | **DONE** | `tests/safety/test_nodes.py::test_distress_is_heard_in_all_three_languages`, 19 cases. `quiero morirme` and `je veux mourir` both returned None before |
| Widening it did not create false alarms | **DONE** | 8 negative cases, including "¿Cuánto me toca ahorrar?", which the first draft escalated |
| An unknown age is treated as a child | **DONE** | `tests/graph/test_account.py`. 148 registered participants with no date of birth were banded adult |
| Prompt injection is blocked | **DONE** | Judging 8; `tests/test_kb_injection.py`, now asserted against the live builder rather than a dead one |
| Grounding enforcement not weakened | **DONE** | `make eval`: `ungrounded_answers_served == 0`, `pii_leaks_into_summary == 0`, `band_violations == 0` |

---

## Security

| Item | Status | Evidence |
|---|---|---|
| Session tokens not minted from client input | **DONE** | `tests/test_rate_limits.py::test_a_guessable_session_id_is_replaced`. 56 conversations had ids under 30 characters |
| Chat rate limit cannot be reset by the caller | **DONE** | `test_a_turn_is_not_metered_against_the_id_the_caller_chose`, verified to fail against the old keying |
| Session minting is rate limited | **DONE** | `test_minting_a_session_is_metered`. It had no limit at all |
| Voice endpoints require a session | **DONE** | `tests/voice/test_endpoints.py`, plus a live probe: all three answer 401 with no session, and `/speak` with a real token returns 200 `audio/mpeg` |
| A cached voice line is still metered | **DONE** | `test_a_cache_hit_is_still_metered`. The cache short-circuit sat above the limiter |
| `owns_thread` closed | **NOT DONE** | Narrowed, not closed: 1,998 of 3,779 conversations are unowned and any caller may continue one. New ids are unguessable, so only 56 pre-existing short-id rows remain reachable by name. A real fix needs a schema column — post-judging |

---

## Reliability and speed

| Item | Status | Evidence |
|---|---|---|
| Network calls retry | **DONE** | `tests/test_retry.py`, 6 cases. Nothing in `app/` retried anything before |
| Retrieval is not rebuilt per question | **DONE** | Measured: corpus read 610-720ms → 0.0ms, index build 114-200ms → 3.6ms, identical results |
| Turn latency under 10s p50 | **SEE `reports/latency/freeze.txt`** | Baseline was `t_total` p50 10.2s. Holding prose for the gates moves cost from after-delivery to before it, so the honest number is `t_total`, not `t_ttft` |
| Composer does not drop keystrokes | **PARTLY** | The guaranteed half is fixed: the mount effect no longer overwrites what was typed. The rest depends on React hydration timing, which needs measuring in a browser rather than reasoning about |
| Both email links work | **DONE** | `tests/test_email_links.py`, 4 cases, pinning both purposes in both directions |
| Memory has no blind spot | **DONE** | The summary boundary now matches the verbatim window; messages 7-12 back were in neither |
| Graph compiled once at startup | **NOT DONE** | Stretch item, deliberately untouched. The plan forbids the parallelisation work it sits next to |

---

## Discoverability and identity

| Item | Status | Evidence |
|---|---|---|
| Landing page reveals games and tutoring | **DONE** | Verified in the browser: four chips render, covering explain / join / teach / play |
| Persona renames | **BLOCKED** | Needs the SKN name shortlist. The display-name layer is where it would go; no mechanism built, because building one for names that may not arrive is speculative |
| An unknown persona keeps child-safety wording | **DONE** | `FALLBACK` moved from `aurora` to `stella`; `test_an_unknown_persona_falls_back_to_the_most_restrictive_card`, which previously passed either way |
| Tests certify the prompt that ships | **DONE** | Retargeted at the live layers. Doing so revealed a rule the shipped prompt had lost |

---

## Open decisions, all needing an answer before the 20th

1. **Conversation-memory questions are answered from the corpus.** One run recalled the planted fact; the next invented "a laptop or a trip", cited. Neither the citation check nor the relevance floor discriminates.
2. **Spanish and French answers carry no follow-up chips.** Serving the English corpus questions would contradict the reply-language rule.
3. **`MEMORY_WINDOW_ENABLED`** is a live `false` in `.env.example` under a comment saying "OFF by default", against a code default of `true`. If production was provisioned from that file, memory is off there and the memory case fails against the deployed URL while passing locally.
4. **Tracing does not exist.** No LangSmith, OTel or Sentry config anywhere; the packages are transitive only.
5. **The contact details want confirming with the client.** They are sourced from the corpus, not invented, but a stale number on a government service is a visible error.

## Not run

**The deployed-URL judging run.** `--against` is built and its readiness probe is
verified against production, but the run writes real rows, spends real model
calls, and case 5 raises a real escalation ticket someone monitors. It belongs
in the freeze window, with the team warned.
