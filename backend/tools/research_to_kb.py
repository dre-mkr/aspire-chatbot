"""Research PDFs into knowledge-base rows, offline, using Pinecone Assistant.

This is a tool on the workbench. It is not a part in the engine.

Nothing here runs while a reader is waiting, nothing in `app/` imports it, and
the live retriever -- pgvector, BM25, RRF fusion, the cross-encoder -- never
learns that Pinecone exists. Research documents go in, Category / Question /
Answer rows come out, a person reads them, and the approved rows are appended to
`data/knowledge_base.csv` and embedded by the ingest that already exists.

    python tools/research_to_kb.py --create
    python tools/research_to_kb.py --upload docs/research/*.pdf
    python tools/research_to_kb.py --extract --audience child \\
        --topics tools/topics.txt \\
        --source-url "https://example.org/the-paper" \\
        --out review/child.csv
    python tools/research_to_kb.py --append review/child.csv --as-of 2026-08-19
    python -m app.ingest

WHY ONE AUDIENCE PER RUN
    Eight per cent of what this bot knows is written for a child -- 57 rows out
    of 706 -- and the youngest persona covers ages five to twelve. So `--extract`
    refuses to run without `--audience`, and says which audience it is writing
    for in the prompt itself. Running it without one just produces another two
    hundred rows for the readers who are already well served.

WHY THE REVIEW GATE IS NOT OPTIONAL
    This is a bot that answers children asking about money. A misread figure
    reaching that audience unreviewed is the one failure nobody would forgive,
    so `--append` refuses while any row is still marked `needs_review=yes`. The
    cost of the gate is that somebody clicks approve.

Pinecone is imported lazily, inside the two steps that need it. `--extract` and
`--append` -- the only steps that touch this repository's data -- run without
the package installed at all.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Final, Iterable, Sequence

#: `backend/`, whichever directory the script is invoked from.
ROOT: Final[Path] = Path(__file__).resolve().parent.parent

#: The one file `--append` may write to.
KNOWLEDGE_BASE: Final[Path] = ROOT / "data" / "knowledge_base.csv"

#: The assistant is created once, ever, and its instructions govern every answer.
ASSISTANT_NAME: Final[str] = "aspire-research"

#: Provenance in the id itself.
#:
#: Every citation panel shows it, and one filter removes every research row if a
#: batch turns out badly. Never `ASP-`, which is the programme's own material.
ID_PREFIX: Final[str] = "RES-"

#: The knowledge base's columns, in order.
KB_COLUMNS: Final[tuple[str, ...]] = (
    "id", "category", "subcategory", "question", "answer",
    "keywords", "audience", "source_url", "as_of",
)

#: What a reviewer reads: the row, plus why it was flagged.
REVIEW_COLUMNS: Final[tuple[str, ...]] = (*KB_COLUMNS, "needs_review", "why")

#: The audience values the retriever already routes on.
#:
#: A sixth value is not a new string, it is an edit to an allowlist
#: (`AUDIENCE_TAGS` in `app/agents/qa/nodes.py`) that silently drops anything it
#: does not recognise -- the row ingests, embeds, and is then never retrieved,
#: with nothing logged. So the tool refuses a value the serving path cannot use.
AUDIENCES: Final[tuple[str, ...]] = ("child", "student", "parent", "teacher", "general")


# ── the assistant's instructions ─────────────────────────────────────────────

INSTRUCTIONS: Final[str] = """\
You are an extractor, not an author.

1. Use ONLY what is written in the uploaded documents. Never add a fact,
   figure, date, rate or example that is not there.
2. Never state a rule about the ASPIRE programme itself -- eligibility,
   amounts, deadlines, required documents. Those come from the programme's
   own sources, not from research literature.
3. Money is in EC$ and never in any other currency. If a source uses another
   currency, describe the idea without the figure rather than converting it.
4. British and Caribbean spelling: programme, organisation, colour.
5. Return JSON only. No prose before or after it, no code fence.
"""


# ── what gets a row flagged ──────────────────────────────────────────────────

#: Language that reads like a rule about the programme rather than about money.
#:
#: Rule 2 is the one that matters. Without it a research paper about a savings
#: scheme somewhere else quietly becomes an ASPIRE rule, and a plausible but
#: wrong eligibility rule reaches a parent.
_PROGRAMME_RULE = re.compile(
    r"\b(?:eligib\w+|entitled|qualif\w+|deadline\w*|enrol\w*|apply|applies"
    r"|application\w*|register\w*|seeded|withdraw\w*|documents?\s+(?:are\s+)?"
    r"(?:needed|required)|required\s+documents?|must\s+(?:be|bring|provide|have)"
    r"|aspire\s+(?:pays|gives|requires|provides|offers))\b",
    re.IGNORECASE,
)

_PERCENTAGE = re.compile(r"%|\bper\s?cent\w*\b|\bpercentages?\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_FIGURE = re.compile(r"\d")
#: A month name only counts as a date next to a number.
#:
#: "Anyone may apply" is not a date, and neither is "a March towards the goal".
#: Bare month names made every other row read as needing review, which is how a
#: gate stops being read at all.
_MONTH = (
    r"January|February|March|April|May|June|July|August"
    r"|September|October|November|December"
)
_DATE = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH})\b"
    rf"|\b(?:{_MONTH})\s+\d{{1,4}}\b",
    re.IGNORECASE,
)

#: Words above the 5-12 vocabulary ladder, per audience that has one.
#:
#: Mirrors `app/safety/vocab.py` for the bands the youngest persona serves,
#: written out here rather than imported so this tool never pulls the
#: application package -- and its heavyweight dependencies -- into a dev run.
_ABOVE_LADDER: Final[dict[str, tuple[str, ...]]] = {
    "child": (
        "interest", "compound", "investment", "invest", "investing", "return",
        "returns", "percentage", "percent", "inflation", "dividend",
        "portfolio", "credit", "loan",
    ),
}

#: Markers `tests/test_kb_injection.py` asserts the real corpus never contains.
#:
#: `disregard the` is a broad substring that ordinary research prose can trip
#: innocently, which is exactly why a person should look before it is appended.
_INJECTION_MARKERS: Final[tuple[str, ...]] = (
    "ignore all previous instructions",
    "ignore previous instructions",
    "system override",
    "disregard the",
    "you are now an unrestricted",
)

#: Beyond this, an answer has probably merged two ideas.
_LONG_ANSWER_WORDS: Final[int] = 90


def flag(row: dict[str, str], audience: str) -> list[str]:
    """Every reason this row needs a person to look at it."""
    question = row.get("question", "")
    answer = row.get("answer", "")
    both = f"{question}\n{answer}"
    reasons: list[str] = []

    if _PROGRAMME_RULE.search(both):
        reasons.append("reads like a rule about the programme")
    if _PERCENTAGE.search(both):
        reasons.append("contains a percentage")
    if _YEAR.search(both):
        reasons.append("contains a year")
    elif _FIGURE.search(both):
        reasons.append("contains a figure")
    if _DATE.search(both):
        reasons.append("contains a date")

    above = [
        word
        for word in _ABOVE_LADDER.get(audience, ())
        if re.search(rf"\b{re.escape(word)}\b", both, re.IGNORECASE)
    ]
    if above:
        reasons.append(f"above the {audience} vocabulary ladder: {', '.join(sorted(set(above)))}")

    if len(answer.split()) > _LONG_ANSWER_WORDS:
        reasons.append("answer long enough that it may have merged two ideas")

    lowered = both.lower()
    for marker in _INJECTION_MARKERS:
        if marker in lowered:
            reasons.append(f"contains the injection marker {marker!r}")

    return reasons


# ── the knowledge base ───────────────────────────────────────────────────────


def existing_rows() -> list[dict[str, str]]:
    """Every row already in the knowledge base."""
    with KNOWLEDGE_BASE.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def next_id(rows: Iterable[dict[str, str]]) -> int:
    """One past the highest `RES-` number already used."""
    used = [
        int(match.group(1))
        for row in rows
        if (match := re.fullmatch(rf"{ID_PREFIX}(\d+)", (row.get("id") or "").strip()))
    ]
    return max(used, default=0) + 1


def _shown(path: Path) -> str:
    """A path to print: repo-relative when it is in the repo, absolute otherwise."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _ends_with_newline(path: Path) -> bool:
    """Whether the file's last line is terminated.

    `knowledge_base.csv` currently does NOT end with a newline, so appending
    without checking glues the first new row onto the last existing one and
    corrupts both.
    """
    if not path.exists() or path.stat().st_size == 0:
        return True
    with path.open("rb") as handle:
        handle.seek(-1, os.SEEK_END)
        return handle.read(1) in (b"\n", b"\r")


# ── steps ────────────────────────────────────────────────────────────────────


def _assistant() -> Any:
    """The Pinecone Assistant handle. Imported here, never at module scope."""
    try:
        from pinecone import Pinecone
    except ImportError:  # pragma: no cover - depends on a dev-only package
        sys.exit(
            "pinecone is not installed. It is a DEV dependency and must never "
            "reach the running service:\n"
            "    pip install -r requirements-dev.txt"
        )

    key = os.environ.get("PINECONE_API_KEY")
    if not key:
        sys.exit(
            "PINECONE_API_KEY is not set. Put it in your shell, not in .env "
            "and not in the repo -- this key never touches the running service."
        )
    return Pinecone(api_key=key)


def create() -> int:
    """Create the assistant, once, with the instructions that govern every answer."""
    client = _assistant()
    client.assistant.create_assistant(
        assistant_name=ASSISTANT_NAME,
        instructions=INSTRUCTIONS,
    )
    print(f"Created assistant {ASSISTANT_NAME!r}.")
    print(INSTRUCTIONS)
    return 0


def upload(paths: Sequence[str]) -> int:
    """Upload research documents. Assistant does the chunking and the extraction."""
    client = _assistant()
    assistant = client.assistant.Assistant(assistant_name=ASSISTANT_NAME)
    for pattern in paths:
        for path in sorted(Path().glob(pattern)) or [Path(pattern)]:
            if not path.is_file():
                print(f"  skipped (not a file): {path}")
                continue
            assistant.upload_file(file_path=str(path))
            print(f"  uploaded: {path}")
    return 0


_EXTRACT_PROMPT = """\
Write knowledge-base rows for ONE audience: {audience}.

{audience_note}

For each topic below, write one row as a JSON object with these keys:
  "category"    - a short grouping, e.g. "Saving"
  "subcategory" - a short label within it, e.g. "Regular saving"
  "question"    - the question a reader of this audience would actually type
  "answer"      - the answer, in that reader's own words
  "keywords"    - search terms separated by |

Topics:
{topics}

Return a JSON array of those objects and nothing else.
"""

#: What "for this audience" means, said in the prompt rather than assumed.
_AUDIENCE_NOTES: Final[dict[str, str]] = {
    "child": (
        "The reader is a child aged five to twelve. Sentences of about eight to "
        "fifteen words. Never the words interest, compound, investment, return "
        "or percentage. Amounts are EC$1 to EC$100, and examples are local: a "
        "patty at break, a snow cone, bus fare, a bicycle, a Carnival costume."
    ),
    "student": (
        "The reader is a teenager. Direct, no cheerleading. Real terms defined "
        "once on first use. Amounts are EC$50 to EC$300, in EC$ always."
    ),
    "parent": (
        "The reader is a parent or guardian, often under time pressure. Lead "
        "with the answer. Do not explain a money concept unless it is the "
        "question."
    ),
    "teacher": (
        "The reader is a teacher who will repeat this to a classroom. Factual "
        "and structured. Give the common misunderstanding alongside the correct "
        "version."
    ),
    "general": "A general adult reader. Plain, brief, in EC$.",
}


def extract(*, audience: str, topics_path: Path, source_url: str, out: Path) -> int:
    """One audience, one file of topics, one reviewable CSV."""
    topics = [
        line.strip()
        for line in topics_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not topics:
        sys.exit(f"{topics_path} has no topics in it.")

    client = _assistant()
    assistant = client.assistant.Assistant(assistant_name=ASSISTANT_NAME)
    prompt = _EXTRACT_PROMPT.format(
        audience=audience,
        audience_note=_AUDIENCE_NOTES.get(audience, ""),
        topics="\n".join(f"- {topic}" for topic in topics),
    )

    from pinecone_plugins.assistant.models.chat import Message

    reply = assistant.chat(messages=[Message(role="user", content=prompt)])
    content = reply.message.content if hasattr(reply, "message") else str(reply)
    rows = _parse(content)

    start = next_id(existing_rows())
    written: list[dict[str, str]] = []
    for offset, row in enumerate(rows):
        record = {column: str(row.get(column, "") or "").strip() for column in KB_COLUMNS}
        record["id"] = f"{ID_PREFIX}{start + offset:03d}"
        record["audience"] = audience
        record["source_url"] = source_url
        record["as_of"] = ""
        reasons = flag(record, audience)
        written.append(
            {**record, "needs_review": "yes" if reasons else "no", "why": "; ".join(reasons)}
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(written)

    flagged = sum(1 for row in written if row["needs_review"] == "yes")
    print(f"Wrote {len(written)} rows to {out}; {flagged} need review.")
    print("Read every one of them. --append will refuse while any is still marked yes.")
    return 0


def _parse(content: str) -> list[dict[str, Any]]:
    """The assistant's reply as rows, tolerating a code fence it was told not to use."""
    text = content.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        sys.exit(f"The assistant did not return JSON. It said:\n\n{content[:2000]}")
    if isinstance(parsed, dict):
        parsed = parsed.get("rows") or parsed.get("data") or [parsed]
    return [row for row in parsed if isinstance(row, dict)]


def append(review: Path, as_of: str) -> int:
    """Append approved rows to the knowledge base. Nothing here talks to Pinecone."""
    with review.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        sys.exit(f"{review} has no rows in it.")

    # ── the gate ──
    pending = [row for row in rows if (row.get("needs_review") or "").strip().lower() == "yes"]
    if pending:
        print(f"REFUSING: {len(pending)} of {len(rows)} rows are still needs_review=yes.")
        for row in pending[:10]:
            print(f"  {row.get('id')}: {row.get('why')}")
        if len(pending) > 10:
            print(f"  ... and {len(pending) - 10} more")
        print(
            "\nCheck each against the source and set needs_review to no, or delete "
            "the row. This gate is not optional."
        )
        return 2

    known = existing_rows()
    seen = {(row.get("id") or "").strip() for row in known}
    problems: list[str] = []
    for row in rows:
        kb_id = (row.get("id") or "").strip()
        if not kb_id:
            problems.append("a row has no id")
        elif kb_id in seen:
            problems.append(f"{kb_id} is already in the knowledge base")
        elif kb_id.startswith("ASP-"):
            problems.append(f"{kb_id} claims to be programme material; research rows are RES-")
        seen.add(kb_id)
        # An empty source_url does not stay empty: ingest falls through to the
        # injected `source` key and the row is served with the provenance
        # "knowledge_base.csv". Every row must say where it came from.
        if not (row.get("source_url") or "").strip():
            problems.append(f"{kb_id or '(no id)'} has no source_url")
        if (row.get("audience") or "").strip() not in AUDIENCES:
            problems.append(f"{kb_id or '(no id)'} has audience {row.get('audience')!r}")
        if not (row.get("answer") or "").strip():
            problems.append(f"{kb_id or '(no id)'} has no answer")
    if problems:
        print("REFUSING:")
        for problem in problems:
            print(f"  {problem}")
        return 2

    if not _ends_with_newline(KNOWLEDGE_BASE):
        with KNOWLEDGE_BASE.open("a", encoding="utf-8", newline="") as handle:
            handle.write("\r\n")

    with KNOWLEDGE_BASE.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=KB_COLUMNS, lineterminator="\r\n", extrasaction="ignore"
        )
        for row in rows:
            writer.writerow({**{column: row.get(column, "") for column in KB_COLUMNS},
                             "as_of": as_of})

    print(f"Appended {len(rows)} rows to {_shown(KNOWLEDGE_BASE)}.")
    print("Now run:  python -m app.ingest")
    return 0


# ── the command line ─────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research_to_kb",
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    step = parser.add_mutually_exclusive_group(required=True)
    step.add_argument("--create", action="store_true", help="create the assistant, once")
    step.add_argument("--upload", nargs="+", metavar="PDF", help="upload research documents")
    step.add_argument("--extract", action="store_true", help="write rows for ONE audience")
    step.add_argument("--append", metavar="CSV", help="append approved rows to the knowledge base")

    parser.add_argument("--audience", choices=AUDIENCES, help="required by --extract")
    parser.add_argument("--topics", type=Path, help="one topic per line")
    parser.add_argument("--source-url", help="where these rows came from")
    parser.add_argument("--out", type=Path, help="the CSV a person will read")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="YYYY-MM-DD")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.create:
        return create()
    if args.upload:
        return upload(args.upload)
    if args.extract:
        # Deliberate. Without an audience this writes another two hundred rows
        # for the readers who are already well served, which is the exact
        # mistake it exists to avoid.
        missing = [
            name
            for name, value in (
                ("--audience", args.audience),
                ("--topics", args.topics),
                ("--source-url", args.source_url),
                ("--out", args.out),
            )
            if not value
        ]
        if missing:
            sys.exit(f"--extract requires {', '.join(missing)}")
        return extract(
            audience=args.audience,
            topics_path=args.topics,
            source_url=args.source_url,
            out=args.out,
        )
    return append(Path(args.append), args.as_of)


if __name__ == "__main__":
    raise SystemExit(main())
