"""The watcher's two commands, for a cron job and for a person.

    python -m app.watcher run       # fetch, diff, draft, queue -- the nightly step
    python -m app.watcher export --out review/website.csv

`run` is what the scheduler calls: Render cron, or the arq worker's nightly
entry. `export` is what a human calls: it writes the queue as the same review
CSV the research tool in `tools/` produces, every row `needs_review=yes`, so
the path from here to the corpus is the one that already exists: the research
tool's `--append` on the reviewed CSV, then `python -m app.ingest`. The
append gate, not this file, decides what gets in.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path

REVIEW_COLUMNS = ("id", "category", "subcategory", "question", "answer",
                  "keywords", "audience", "source_url", "as_of", "needs_review", "why")


async def _run() -> int:
    from app.watcher.graph import build_watcher_graph

    result = await build_watcher_graph().ainvoke({})
    pages = len(result.get("pages", []))
    print(f"pages={pages} baselined={result.get('baselined', 0)} "
          f"changes={len(result.get('changes', []))} queued={result.get('queued', 0)}")
    return 0 if pages else 1


async def _export(out: Path) -> int:
    from app.watcher.store import mark_exported, pending_rows

    rows = await pending_rows()
    if not rows:
        print("The queue is empty. Nothing on the site has changed since the last export.")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "id": row.kb_id, "category": row.category, "subcategory": row.subcategory,
                "question": row.question, "answer": row.answer, "keywords": row.keywords,
                "audience": row.audience, "source_url": row.source_url, "as_of": row.as_of,
                # Always yes. The watcher has no authority to mark its own work reviewed.
                "needs_review": "yes", "why": row.why,
            })
    await mark_exported([row.kb_id for row in rows])
    print(f"{len(rows)} rows -> {out}. Check each against the page, set needs_review "
          f"to no, then append with the research tool in tools/ (--append {out}) "
          f"and re-embed with: python -m app.ingest")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.watcher")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="fetch the watched pages, queue drafts for review")
    export = sub.add_parser("export", help="write pending rows as a review CSV")
    export.add_argument("--out", type=Path, default=Path("review/website.csv"))
    args = parser.parse_args()
    if args.command == "run":
        return asyncio.run(_run())
    return asyncio.run(_export(args.out))


if __name__ == "__main__":
    sys.exit(main())
