# The voice spine, vendored

`aspire_personas.yaml` is the ASPIRE Voice Kit's **source of truth** for the
structural facts: keys, card files, bands, the enforced word caps, the
vocabulary ladder and the invariants. It arrives from the client, revised
edition 22 August 2026.

It is vendored here rather than referenced because `tests/test_voice_spine.py`
reads it on every run. A document that lives in somebody's Downloads folder
cannot fail a build, and the whole point of this file is that it can.

## What it is not

It is **not loaded at runtime.** Nothing imports it, and the values it carries
are declared independently in `app/safety/vocab.py` and
`app/graph/nodes/safety_out.py`. That duplication is deliberate: the test
compares the two and fails when they disagree, which is what catches a cap
being edited in code without the spine moving, or a spine revision landing
without the code following.

Wiring it up as the runtime source instead would remove the disagreement the
test exists to find.

## When a new kit arrives

Replace this file, run the suite, and read what fails. A failure here is the
revision telling you what it changed.
