"""Three prompt layers, assembled by one builder.

    GLOBAL        product identity and the rules that hold for every agent
    PERSONA_CARD  register, reading level, vocabulary, local references
    AGENT_ROLE    this agent's job

`global_rules.GLOBAL` is one shared constant. `personas/` is one file per
persona, shared across every agent. `builder.build_messages` is the only place
any agent's message list is assembled.

## Why this package exists

The diagnosis found `ASPIRE_SYSTEM_PROMPT` -- 5041 characters of product
identity, XCD-only, never-invent-rates and escalate-vs-guess rules -- with no
consumer anywhere in `app/`. It had been the single prompt behind `/chat`, and
when the graph replaced that, the per-agent prompts written to succeed it
reproduced only the AGENT_ROLE layer. So no live agent received the global safety
rules, and each one independently re-derived or omitted them.

The GLOBAL constant here is that content, split rather than rewritten: the
retrieval-specific sections (GROUNDING, ANSWER-DO-NOT-NARRATE) stayed with the
Q&A role where they belong, and everything true of every agent moved here. No
programme rule was reworded and none was added.
"""

from app.prompting.builder import build_messages
from app.prompting.global_rules import GLOBAL
from app.prompting.personas import persona_card

__all__ = ["GLOBAL", "build_messages", "persona_card"]
