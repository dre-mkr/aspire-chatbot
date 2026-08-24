"""The website watcher: a standalone LangGraph agent that keeps the corpus honest.

The knowledge base was read off aspire.gov.kn by hand and pinned -- the FAQ
check in `tools/check_website_faqs.py` even says so: "If the site changes,
update the list -- and notice that you had to." This package is the noticing,
made mechanical.

It is a SECOND graph in this backend, not a seventh agent in the serving
graph. The six agents run once per reader message; this one runs on a clock
with no reader present (`python -m app.watcher run`, nightly via arq or a
Render cron). Nothing in the serving path imports it.

What it will not do is write to the corpus. The one rule this repository
enforces everywhere -- the review columns, the append gate, the WHY
paragraphs -- is that no unreviewed sentence reaches a child. So the watcher
ends at a queue: drafted rows land in `pending_kb_rows` marked for review,
`python -m app.watcher export` turns them into the same review CSV the
research tool in `tools/` produces, and that tool's `--append` gate (which
this deliberately reuses, WEB- ids and all) is still the only door into
`data/knowledge_base.csv`. The tool's name is deliberately not written here:
a guard test keeps every module under `app/` ignorant of it, and prose does
not get an exemption.
"""

from app.watcher.graph import build_watcher_graph

__all__ = ["build_watcher_graph"]
