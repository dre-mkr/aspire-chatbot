# Objections

Everything here was implemented as specified. This file records where I think the
brief is wrong and why, per its own instruction to implement anyway rather than
substitute a different design silently.

---

## 1. The concurrency contract in §9.1 contradicts the three-tier guarantee in §8.2

**The brief says both of these:**

```python
prose_task = asyncio.create_task(stream_teach(ctx))
async for token in prose_task:
    yield sse_token(token)
```

> **Validate on completion.** If word count is below the band minimum … regenerate
> once with the specific violation quoted.

These cannot both hold. `stream_mode="messages"` forwards tokens as the model
produces them, so by the time a lesson can be measured it has already been read.
"Regenerate once" is not available to a turn whose first attempt is on screen —
the only options left are to append a correction (which reads badly) or to serve
the failure.

**What I implemented, and why.** Generate whole → validate → retry once → floor →
emit. The tutor node is on `INTERNAL_NODES`, so no raw model token reaches a
reader, and the validated lesson goes out explicitly on the custom channel.

I chose the guarantee over the streaming because the guarantee *is* the fix for
the reported symptom and the streaming is a latency property. But I want the cost
recorded plainly: **time-to-first-token on the prose is now full generation time.**
For a 180-word Orion lesson on `gpt-5.6-luna` that is seconds, not milliseconds,
and a reader watching a blank pane does not know a lesson is coming.

Two things make it defensible rather than merely chosen:

* `plan_widget`'s model call used to sit in front of the teaching call on the
  critical path. It does not any more. A turn spends roughly what it did before
  its first token and spends it on the lesson rather than on choosing a slider.
* The widget's two model calls now overlap the teaching call entirely, where
  before they were serial.

**What I would build instead, given more time.** Stream tier 1 behind a
short *hold* — buffer the first N tokens, and once enough have arrived to
establish that the lesson is not going to be trivially short, release the buffer
and stream the rest live. That gets streaming for the common case and keeps a
regeneration available for the failure it is meant to catch. It needs a token
budget calibrated per band and it needs the interceptor to learn a "hold then
release" mode, which is more machinery than this workstream should add on top of
everything else it changed.

---

## 2. Four bands is the wrong number for this product

The brief specifies `body_5_8`, `body_9_12`, `body_13_18`, `body_adult`, and
personas Stella / Orion / Aurora / Nova.

This product has **five** bands — `5-8`, `9-12`, `13-15`, `16-18`, `adult` —
and they are not decoration. `safety_out.WORD_CAPS`, `validate.BAND_KINDS`,
`BAND_CONTROL_CAP`, `BAND_LABEL_WORDS`, the vocabulary ladder in `safety/vocab.py`
and the curriculum's `for_band` inheritance are all keyed on the five. In
particular `BAND_KINDS` gives 16-18 the full nine primitives and 13-15 fewer,
and `BAND_WIDGET_BUDGET` gives 16-18 two widgets a turn and 13-15 one.

A four-band concept schema would need translating at every read site, and a
translation layer between the concept table and the band ladder is a place for
them to disagree about who a thirteen-year-old is.

**Implemented with five columns.** `body_13_15` and `body_16_18` are separate. The
brief's "Orion 13–18: 90–180 words" is applied to both.

---

## 3. The seven gates in §9.3 are not the seven gates this product has

The brief lists `PARSE SCHEMA NUMERIC BAND SANITISE LOCALE PROVENANCE`. The
repository has `parse schema band numeric formula copy budget`, and the
differences are not cosmetic:

| Brief | Reality |
|---|---|
| SANITISE as its own gate | folded into `schema` — `SafeText` rejects markup, URLs and literal colours at validation |
| — | **`formula`**, which the brief has no equivalent of: it evaluates a simulator's maths at every corner and midpoint of the control box |
| — | **`copy`**, which checks every string against the band's vocabulary ladder |
| — | **`budget`**, one widget a turn, two from 16-18 |
| LOCALE | absent |
| PROVENANCE | partly in the transport, not the validator |

Reordering to match the brief would have deleted `formula` and `copy`, which are
the two gates that catch the failures a child would actually notice — a slider
that produces a negative balance at its extreme, and a label using a word the
band has not met.

**Implemented as nine gates**: the existing seven, unchanged and in their existing
order, plus `locale` and `provenance` added in `agents/learn/widgets.py`. They
live there rather than in `validate.py` because both are properties of the *turn*
(what language is this conversation in, which agent is speaking) rather than of
the widget, and `GateContext` is deliberately kept small.

---

## 4. "All arithmetic runs in Python" is stated but not fully enforceable at build time

The rule is right and I have implemented it at runtime: `numeric_anchors` are
handed to the model as the only permitted numbers with an explicit instruction not
to derive from them, and the formula registry computes everything else.

At **build** time, Pass C's model necessarily produces numbers — that is what
generating a worked example means. Pass D re-derives them in Python and rejects
anything untraceable, which is the enforcement the brief actually asks for. But it
is *detection*, not *prevention*, and the distinction shows in the results: 4 of 69
concepts still carry violations after a regeneration, and their offending bodies
are nulled rather than corrected.

The honest framing is that build-time grounding is a filter with a measurable
escape rate, not a guarantee. It is reported as such in the completion report
rather than described as "zero grounding escapes".

---

## 5. `concepts` already existed, and the brief's `CREATE TABLE` would have orphaned live data

The brief specifies `CREATE TABLE concepts (id text PRIMARY KEY, …)`. That table
exists (migration 0011), holds the authored curriculum's five concepts, and is the
target of two foreign keys: `mastery.concept_id` and `lessons.concept_id`.

Creating it fresh would fail; creating a parallel table would mean two answers to
"what has this child learned" and two id spaces for spaced repetition to reconcile.

**Implemented as an extension in place.** Existing rows keep their ids and gain
`slug = id`; seeded rows get `CON-####`; `module_id` becomes nullable because a
synthesised concept belongs to no authored module. The upsert keys on
`(slug, locale)` rather than on the primary key, so a rerun cannot orphan a mastery
row by renumbering.

---

## 6. Minor: the 0.9 embedding-similarity dedup in Pass A is the wrong tool

The brief says to deduplicate the taxonomy "by embedding similarity > 0.9". I used
Jaccard overlap over title tokens at 0.7 instead.

The near-duplicates at this scale are lexical — `savings_goal` / `saving_goals` /
`setting_a_goal` — and a token test catches them exactly, costs nothing, and is
inspectable in `taxonomy.json` by whoever reviews it. Embedding a few hundred short
titles would add a network dependency (and a 403 failure mode) to a pass that
currently has none.

It under-merged: 123 proposals became 114 concepts, above the brief's 40–70 target.
Recorded as a real shortfall in the completion report rather than defended.

---

## 7. Not an objection to the brief — a correction to its diagnosis

The brief's hypothesis was that the inline sentinel path is "the most likely cause
of the reported symptom". It is *a* cause, it is real, and the mechanism is exactly
as predicted (`stream_interceptor.py:381` discards the buffer, taking every token
after the marker with it).

But it is the **second** cause. The first is that `resume_or_place` never read the
learner's message at all — `scheduler.place()` takes no utterance parameter
([learn/graph.py:120](../backend/app/agents/learn/graph.py#L120)) — so the turn
served whatever lesson was next in the spaced-repetition schedule. "The learning
agent does not return real explanations of the topic the user asked about" was
literally true: it returned a competent explanation of a different topic.

That distinction matters for what gets fixed. Removing the sentinel alone would
have produced complete, well-formed lessons about the wrong thing.
