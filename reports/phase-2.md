# Phase 2 — the five things the client will personally test

2026-08-14 · branch `fix/judging-readiness` · continues `phase-0-1.md`

Seven commits. The judging suite went **8/12 → 11/13**, and the persona probe is
9/9. Both remaining failures are the same defect, and it is T3.1's.

| | after Phase 1 | now |
|---|---|---|
| judging (signed out, 13 cases) | 8/12 | **11/13** |
| persona probe (stella, orion, aurora) | — | **9/9** |
| spurious declines | 2 of 27 | 1 of 22 |
| `locale` re-prompts per run | 2 | 1 |

---

## What landed

**T2.1 — contact details.** `GLOBAL` told the model to offer ASPIRE's details
and, two lines earlier, never to invent one. Both pinned load-bearing, and
neither satisfiable: nothing in the composed prompt said what they are. Now
config-backed from the corpus rows, in the prompt, and in every adult decline.

**T2.2 — the persona picker.** The "URL flips back" report is a frontend cache
and no backend change could have fixed it. `graphSession` held one token per
THREAD and returned it whatever was asked for. The same bug hit language, which
is the more interesting half: switching to French mid-thread left the turns
running as `en`, which is how a French answer could arrive with an English
decline welded on. Held per (thread, persona, language) now. `FALLBACK` moves
from `aurora` to `stella`.

**T2.3 — the eligibility gate.** Twelve phrasings asking about the RULES or the
PROCESS were filed as personal intent, and the card carries no prose, so asking
one got you a form and no answer. Two harnesses neither built for this pointed
at the same patterns: `golden.yaml` expected `en-02` and `en-03` answered, and
the latency probe measured five of thirty golden questions producing no visible
token at all.

**T2.4 — language and voice.** No layered prompt said what language to answer
in; the words "language" and "locale" appear in none of them, and
`SessionContext.locale` was carried into `build_messages` and never used. The
band was equally implicit. And every reader was read to in the STAFF voice --
`speakStream` sent `nova` for all of them, while the backend registry was
already persona- and language-aware and startup-validated. Only the client never
said who was speaking. The learn agent's decline is localised too.

---

## T2.5: not done, and the measurement is why

The task says answers overshoot the age word-caps, that the length gate
regenerates the whole answer, and that this is "the top suspect" for 20-28s
turns. Measured across 22 turns and all four bands:

| band | QA cap | median answer | longest | length re-prompts |
|---|---|---|---|---|
| 5-8 | 120 | 39 | 101 | **0** |
| 9-12 | 180 | 65 | 159 | **0** |
| 16-18 | 400 | 41 | 92 | **0** |
| adult | none | 113 | 125 | **0** |

The length gate never fires, on any band, and no answer comes close to its cap.
The prompt conflict is real -- `QA_AGENT_ROLE` says "be thorough… conditions,
exceptions, amounts, deadlines" while `orion.md` says "answer the question that
was asked, then stop" -- but the personas and `global_rules`' "lead with the
answer" are already winning. Rewriting the role card would be changing a prompt
days before a demo to fix a symptom that does not occur.

It also means the latency is not coming from there. TTFT p50 by band: 7.3s at
16-18, 8.6s at 9-12, 10.4s at 5-8, 11.2s at adult. Whatever is spending those
seconds, it is not answer regeneration.

The half of T2.5 with a real gap is chips: 8 of 13 answers carry them, and the
two that should and do not are the Spanish and French turns. Recorded as a
decision rather than fixed, because the obvious fix -- serving the English
corpus questions -- now contradicts the reply-language rule.

---

## Interactions the work created, both found by running rather than reasoning

Adding contacts to the prompt broke the grounding check. `+1 (869) 667-5566`
reaches the model from the prompt, not from a retrieved extract, so
`unattributed_figures` read it as three inventions -- 869, 667, 5566 -- and
declined every answer that offered the number the prompt had just told it to
offer. Three declines in one thirteen-turn run. T2.1 was making things actively
worse until that was fixed.

The PII gate would have done the same thing for the same reason, and that one
was anticipated: `_PHONE` matches the programme's own number, so the decline
would have rendered "[a phone number]".

Both exemptions are narrow and tested in both directions: a reader's own number
is still redacted, and a figure the corpus does not have is still caught.

---

## Corrections to my own work

A first draft of the contact change added the website to the CHILD decline copy
and broke `test_a_child_is_pointed_at_a_grown_up_not_a_website`. That decision
has a test naming it and the reasoning holds -- handing a nine-year-old a phone
number routes them around the adult who is meant to be between them and the
programme -- so it was reverted rather than argued with.

Two judging cases were testing the wrong thing and were reworded. Case 9 asked
"¿Puede mi hija participar?", which is a PERSONAL eligibility question and now
correctly opens the wizard; it only ever reached the model because the gate
claimed everything. Case 11 asked for a Miami capital-gains rate, which the
model refuses on its own and well, pointing at a tax professional and never
touching the decline path -- and sending that reader to ASPIRE would have been
the wrong referral anyway.

`initial_state` declared `identity_proven` and never set it, so every fixture
read it as absent, and absent is falsy. Nothing in `app/` calls that helper, so
it only ever bit tests -- five at once, the moment anything keyed on the flag.

---

## Not done, deliberately

The brief asks to widen complaint detection, on the theory that a registration
slot answer containing "unacceptable" could hijack the turn. Measured against
realistic slot answers -- a name, an island, "I am their mother", a date, "no",
"skip" -- none trips `is_complaint`. What does trip it is "This is
unacceptable", where escalating is the right call. There is no defect.

The starter chips are left alone: chips 2 and 3 were worded to hit exactly the
patterns T2.3 moved, so they now answer correctly with no frontend change, and
repointing them at games and tutoring is T4.2's job rather than touching the
same two strings twice.

---

## Open decisions, carried forward

- What follow-up chips a Spanish or French answer should carry.
- How conversation-memory questions are answered -- one run recalled the planted
  fact, the next invented "a laptop or a trip", cited.
- `MEMORY_WINDOW_ENABLED` reads `false` in `.env.example` under a comment saying
  "OFF by default", against a code default of `true`.
- Tracing does not exist. "Enable tracing" means choosing and adding one.
- `owns_thread` still admits any caller to an unowned conversation. Narrowed by
  T1.3 rather than closed.
- "The assistant could not be reached" is still unattributed. Leading hypothesis
  is an un-retried transient, which is T3.3.
