# The ASPIRE Path

How ASPIRE moves somebody forward, and how it shows them that it is doing it.

Companion to `HOOK_SPINE.md` and `EDUCATOR_SPINE.md`, and deliberately not one
of them — see *On the word "spine"* at the end, which is the one section a
reader who names things around here should not skip.

The governing rule, from which everything else follows:

> **A turn has done its job when the reader is closer to the thing they came
> for — not when a question has been answered.**

Answering is the easy half. A reader who asks how to save for a laptop and
receives a correct paragraph about saving has been answered and not moved. The
Path exists to make the second half the default, and to make it visible while
it happens.

## The six stages

They spell the product, which is why this needs no other name:

| | Stage | What ASPIRE is doing |
| --- | --- | --- |
| **A** | Aim | Understand the real objective, not just the sentence |
| **S** | Source | Find it in the approved material, and check it |
| **P** | Plan | Break the objective into what has to happen |
| **I** | Interact | Calculate, compare, simulate, teach, play |
| **R** | Recommend | The one next move |
| **E** | Enable | Make that move possible |

**`Enable`, not "execute".** This assistant is bounded on purpose. It can build
a plan, open a simulator, produce a checklist, prepare a lesson, hand a parent
to Imani, or route to the ASPIRE team. It cannot act on anybody's account —
`servicing_agent` exists to say exactly that — and a stage named for authority
it does not have would be the one dishonest word in the sequence.

## What the reader sees

Not this table. Six stages is a diagram; a reader glancing at a progress strip
reads four things and skims six. Each guide folds the six into their own three
or four, in their own register and their own language:

| Guide | Visible Path |
| --- | --- |
| Skye · 5–8 | Finding out → Trying it → Your turn |
| Kaleb · 9–12 | The answer → The reason → Your challenge |
| Zion · 13–18 | Your goal → Facts checked → Your plan → Next move |
| Imani · parents | What you need → What to prepare → Who acts → Next step |
| Azuri · educators | Need understood → Source checked → Adapted → Ready to use |
| Guest | Understanding → Checking → Guiding |

Kaleb's is not a new idea. His persona card has said *"Answer. Reason.
Challenge. In that order, every time."* since he was written; the Path shows a
rhythm he was already keeping. Skye gets three because a five-year-old counts to
three. Guest stays plain because nothing is known about that reader yet, and a
Path that promises personalisation before it has any is a lie with a tick next
to it.

## What it never shows

No classifier, no retrieval score, no node name, no model, no tool call, no
chain of thought. A reader is shown what the work *means to them*. There is a
test asserting that no stage name in any language contains a word from the
machinery, because the pressure to leak one grows every time somebody wants the
product to look clever.

## When it stays silent

A question with an answer is not a journey. Drawing four stages over
*"what is compound interest?"* is theatre, and theatre is what makes a product
feel less trustworthy rather than more.

No Path for:

- **servicing** — the honest answer is one sentence and a phone number
- **escalation** — handing to a human is not a plan to watch being built
- **a story** — one long generation, not a sequence of steps
- **small talk** — nothing is being worked through

## Why it exists at all

Nothing in this product streams tokens. `api/stream.py` holds every word until
`safety_out` has run, because a word cap, a vocabulary swap or a decline lands a
graph step *after* the agent that wrote the text, and anything already on screen
cannot be taken back. That call is right and it is staying.

Its cost is a silence. Measured on production across twenty-four consecutive
turns: **between 1.5 and 14.7 seconds, mean 6.9**, with nothing on screen.

Path frames carry no answer, no figure and no claim — a stage index into labels
the server chose — so they do not wait for the outbound gates, and they leave the
moment a real node finishes. The reader watches the work instead of a blank
screen, and what they watch is true.

## The outcome test

Every agentic turn should be able to answer one question internally:

> **Did the reader leave this turn closer to their objective?**

Not *did we answer*. If the honest answer is no, the turn ended one stage early
— usually at `Recommend`, with information delivered and no next move named.

## On the word "spine"

Five things here are already called one, and they agree about what it means: a
governing contract about **how ASPIRE speaks** to a particular audience.

| | What it governs |
| --- | --- |
| the **Voice Spine** — `prompting/spine/aspire_personas.yaml` | the client's own source of truth: keys, bands, word caps, the vocabulary ladder |
| the **Educator Spine** — `docs/EDUCATOR_SPINE.md` | what may be told to a professional who will act on it |
| the **Hook Spine** — `docs/HOOK_SPINE.md` | how a greeting earns the right to say anything specific |
| the **Adult Learner spine** | the register for an adult learning for themselves, explicitly not the educator's |
| `teach._spine()` | the points a lesson must cover |

Every one is about what is **said**. The Path is about what is **done**, which
is a different category. A sixth meaning — the first that is not about speech —
would cost the other five their precision, and the Voice Spine is a document
that arrives from the client, so the word is not ours to widen.

The acronym is the asset. It does not need a noun in front of it.
