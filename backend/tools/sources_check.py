"""Check the knowledge base's sources against the registry, or canonicalise one URL.

Two jobs, both for whoever is editing `data/sources.yaml` or adding rows to the
knowledge base.

    python -m tools.sources_check
        Reads every `source_url` in the corpus and reports what each one would
        cite as. Names anything the registry does not cover and anything that
        would not validate. Exit 1 if a row would cite nothing at all.

    python -m tools.sources_check https://www.aspire.gov.kn/Some/Page/
        Prints the canonical form -- the key a `pages:` entry is written
        against -- along with the link that would be rendered and the name it
        would carry.

Nothing here writes anything. It exists because `sources.yaml`'s keys are
canonical and the CSV's values are not, and guessing at that by hand is how a
`pages:` entry ends up silently never matching.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import sources  # noqa: E402
from app.config import get_settings  # noqa: E402


def _corpus_urls(csv_path: Path) -> Counter[str]:
    """Every distinct `source_url` in the knowledge base, with its row count."""
    counts: Counter[str] = Counter()
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            counts[(row.get("source_url") or "").strip()] += 1
    return counts


def _describe_one(url: str) -> int:
    """Print what one URL would become. Returns a process exit code."""
    print(f"given      {url}")
    print(f"canonical  {sources.canonical(url) or '-- will not validate --'}")
    print(f"link       {sources.safe_url(url) or '-- not linkable --'}")

    ref = sources.describe({}, stored_url=url)
    if ref is None:
        print("cites as   -- nothing; this row would carry no source --")
        return 1
    print(f"cites as   {ref.label}")
    print(f"domain     {ref.domain or '--'}")
    return 0


def _audit(csv_path: Path) -> int:
    """Print a line per distinct source in the corpus. Returns an exit code."""
    counts = _corpus_urls(csv_path)
    if not counts:
        print(f"{csv_path} has no rows.", file=sys.stderr)
        return 1

    unnamed: list[str] = []
    unlinkable: list[str] = []
    registry = sources.registry()

    print(f"{sum(counts.values())} rows, {len(counts)} distinct sources\n")
    for url, rows in counts.most_common():
        ref = sources.describe({}, stored_url=url)
        if ref is None:
            unnamed.append(url or "(blank)")
            print(f"{rows:5}  !! NO SOURCE   {url or '(blank)'}")
            continue

        # A source named only by its own domain has no `sites:` entry; a page
        # named off its path has no `pages:` entry. Both work and both are
        # worth a nudge, because a hand-written name reads better.
        flag = " "
        if ref.url:
            key = sources.canonical(ref.url) or ""
            if ref.domain not in registry.sites:
                flag = "s"
            elif key not in registry.pages:
                flag = "p"
        elif not ref.url and url and not url.lower().startswith(sources.DOCUMENT_SCHEME):
            unlinkable.append(url)
            flag = "!"

        print(f"{rows:5}  {flag}  {ref.label[:58]:60} {ref.domain}")

    print()
    if unnamed:
        print(f"{len(unnamed)} source(s) cite NOTHING -- fix the corpus rows:")
        for url in unnamed:
            print(f"  {url}")
    if unlinkable:
        print(f"{len(unlinkable)} source(s) look like URLs but will not validate:")
        for url in unlinkable:
            print(f"  {url}")
    if not (unnamed or unlinkable):
        print("Every source resolves. `s` = no sites: entry, `p` = no pages: entry.")

    return 1 if (unnamed or unlinkable) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "url", nargs="?", help="Canonicalise this one URL instead of auditing the corpus."
    )
    parser.add_argument("--csv", type=Path, default=None, help="Override the corpus path.")
    args = parser.parse_args()

    if args.url:
        return _describe_one(args.url)

    settings = get_settings()
    csv_path = args.csv or settings.resolved(settings.knowledge_base_csv)
    if not csv_path.exists():
        print(f"No knowledge base at {csv_path}.", file=sys.stderr)
        return 1
    return _audit(csv_path)


if __name__ == "__main__":
    raise SystemExit(main())
