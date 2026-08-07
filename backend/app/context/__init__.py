"""One object describing who is talking and what has happened so far.

`session_context.SessionContext` is the shape; `resolver.resolve_context` is the
node that fills it in, once per turn, before routing. Everything downstream reads
the object instead of re-deriving its fields.

The diagnosis counted seven places where a downstream node recomputed something
the graph already knew, and three independent defaults for `age_band` alone
(`learn/graph.py:86`, `teach.py:338`, `teach.py:270`). That is what this package
replaces.
"""
