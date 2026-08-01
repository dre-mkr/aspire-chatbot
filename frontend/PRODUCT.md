# ASPIRE AI — Product

> Derived from the codebase on 2026-08-01 during a design review, not from an
> interview. Lines marked **ASSUMED** are inferences from code and were not
> confirmed by a human — correct them before treating this as settled.

## What it is

A conversational financial-literacy assistant for the **ASPIRE programme in
St. Kitts and Nevis**. A young person asks a question about money, investing, or
the programme itself, and gets a short, sourced, plain-language answer they can
hear read aloud, check against its sources, and sometimes practise as a game.

It is one screen. There is no dashboard, no account, no feed.

## Who uses it

Four audiences exist in the domain model (`backend/app/games/models.py`):

| Persona  | Plays games | ASSUMED role                          |
|----------|-------------|----------------------------------------|
| `stella` | yes         | Young account holder                   |
| `orion`  | yes         | Young account holder                   |
| `aurora` | no          | Parent / guardian                      |
| `nova`   | no          | Mentor or programme staff              |

Only `stella` and `orion` are in `PLAYING_PERSONAS`; games are "a learning
activity for account holders", and a parent asking about them "wants to know
what their child is doing, not to play."

**No client selects a persona yet.** `AspireChat` takes a `persona` prop that
nothing passes, and unset means *unknown*, which the backend treats as
permissive rather than as any particular audience. So the shipping UI is the
unknown-persona UI, and that is the one this review judges.

The interface is written for a child or teenager: "A grown-up can turn this off
in voice options", an "Explain it simply" toggle, games with letter tiles, and a
disclaimer that points at a **mentor** rather than at a lawyer.

## The primary task

**Ask a question, get an answer you can trust.** Everything else is in service
of that:

- **Sources** — every answer can be opened to show the knowledge-base extracts
  behind it. Collapsed by default: it is the evidence, not the answer.
- **Explain it simply** — asks for plainer language without changing the facts.
- **Read aloud** — answers can be spoken, at 4 speeds, in English, Spanish or
  French.
- **Ask by voice** — hold Space or press the mic; audio becomes text in the
  composer for review, and is then deleted. Nothing sends on its own.
- **Games** — a True/False or Word Scramble card appears *inside the transcript*
  when the assistant starts one through its own tools. The lesson happens where
  the talking happens.
- **History** — past conversations, on this device only. There is no account.

## Constraints that are already decided

- **Light only.** `color-scheme: light only`. The brand gradient carries the
  contrast; a dark theme would fight it. Not a gap — a decision.
- **No account.** The rail foot says "Not signed in · Chats are saved on this
  device" rather than dressing up a signed-in user.
- **The backend is a separate FastAPI service** (`VITE_ASPIRE_API_URL`, default
  `http://localhost:8000`). The browser calls it directly.
- **Games are additive.** If the games endpoint is off or unreachable, the card
  does not appear and the conversation is unaffected.
- **Voice is optional.** If it is unavailable the controls disappear rather than
  sitting there disabled.
- **Answers stream** with a typewriter reveal (40ms tick, 4 words), which is
  suppressed under `prefers-reduced-motion`.

## What success looks like

**ASSUMED**, from the shape of the code rather than a stated goal:

1. A young person gets a usable answer to a money question without a mentor
   present.
2. They can tell where the answer came from, and are told to check important
   things with a mentor.
3. Reading ability is not a barrier — voice in, voice out, and plain-words mode
   all exist to remove it.

## Surface mode

**Operate.** This is app UI: the visitor completes a task (get an answer). The
landing screen is the empty state of that task, not a marketing page — it has no
pitch, no pricing, no signup, and its only call to action is the composer.
Scanability and native expectations outrank expression; the brand lives in the
gradient, the orb, and the details.
