"""The escalation contract: what a handoff to a person must carry.

Deliberately separate from `app.agents.escalate`, which is the subgraph that
*performs* an escalation. This package holds the rules about when one is
permitted and what it must say; that one holds the nodes that open a ticket and
write the reply. The two names are uncomfortably close and the split is worth
it: the contract is imported by the router, the QA subgraph and the pre-router
gate, none of which should be importing an agent's internals.
"""
