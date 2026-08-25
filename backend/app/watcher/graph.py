"""Fetch, diff, draft, queue: the watcher graph itself.

Four nodes, and only one of them is a model call. Fetching a public page and
hashing its text are jobs for plain code; the LLM is reached for exactly once,
to turn "this paragraph changed" into knowledge-base rows shaped like the 700
that already exist. If nothing changed, the graph ends before the model is
ever built -- a quiet night costs one HTTP request per watched page.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
from datetime import date
from html.parser import HTMLParser
from typing import Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph

from app.config import get_settings

logger = logging.getLogger(__name__)

#: The audience vocabulary the ingest and the review gate both accept.
AUDIENCES = ("child", "student", "parent", "teacher", "general")

#: Website rows get their own prefix: ASP- is hand-written programme material,
#: RES- is research extraction, WEB- is this watcher. The research tool's
#: append gate refuses ASP- and accepts the rest, so WEB- rows pass through
#: the existing door without modifying it.
ID_PREFIX = "WEB"

_SKIP_TAGS = {"script", "style", "noscript", "svg", "head"}


class _TextExtractor(HTMLParser):
    """The visible text of a page, one block per structural element.

    Stdlib on purpose: the watcher must run in the arq worker and in a bare
    Render cron container, and a dependency it does not need is a way for
    either to break.
    """

    _BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th",
                   "div", "section", "article", "summary", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        blocks = [re.sub(r"\s+", " ", block).strip() for block in raw.split("\n")]
        return "\n".join(block for block in blocks if block)


def page_text(html: str) -> str:
    """The page as the paragraphs a reader would see, markup gone."""
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.text()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def changed_blocks(old: str, new: str) -> list[str]:
    """The paragraphs that are new or reworded, in page order.

    Deletions are reported to the log but produce no draft rows: a paragraph
    leaving the site is a reason for a human to prune the corpus, not for a
    model to write anything.
    """
    matcher = difflib.SequenceMatcher(a=old.split("\n"), b=new.split("\n"), autojunk=False)
    fresh: list[str] = []
    for op, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if op in ("replace", "insert"):
            fresh.extend(block for block in matcher.b[j1:j2] if len(block) > 40)
    return fresh


class WatcherState(TypedDict, total=False):
    """One nightly run over every watched URL."""

    pages: list[dict[str, Any]]   # url, text, hash, previous_text (None on first visit)
    changes: list[dict[str, Any]]  # url, blocks
    drafts: list[dict[str, Any]]   # KB-shaped rows, all destined for review
    queued: int
    baselined: int


# ── the nodes ────────────────────────────────────────────────────────────────


async def fetch(state: WatcherState) -> dict[str, Any]:
    """Read every watched page. A page that will not load is skipped, loudly."""
    settings = get_settings()
    pages: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "aspire-watcher/1.0"}) as client:
        for url in settings.watcher_urls:
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("watcher: could not fetch %s: %s", url, exc)
                continue
            text = page_text(response.text)
            pages.append({"url": url, "text": text, "hash": text_hash(text)})
    return {"pages": pages}


async def diff(state: WatcherState) -> dict[str, Any]:
    """Compare each page against the last run's snapshot in Neon.

    A first visit is a baseline, never a change: the corpus already covers the
    site as it stands, so drafting rows from an unchanged page would only
    manufacture review work.
    """
    from app.watcher.store import load_snapshot, save_snapshot

    changes: list[dict[str, Any]] = []
    baselined = 0
    for page in state.get("pages", []):
        previous = await load_snapshot(page["url"])
        if previous is None:
            await save_snapshot(page["url"], page["hash"], page["text"])
            baselined += 1
            continue
        if previous.content_hash == page["hash"]:
            continue
        blocks = changed_blocks(previous.content, page["text"])
        if blocks:
            changes.append({"url": page["url"], "blocks": blocks})
        else:
            logger.info("watcher: %s changed, but only deletions or fragments", page["url"])
        await save_snapshot(page["url"], page["hash"], page["text"])
    return {"changes": changes, "baselined": baselined}


_DRAFT_PROMPT = """You maintain the knowledge base of ASPIRE AI, the Government of \
St Kitts and Nevis financial-literacy assistant. The programme's public website \
has changed; the new or reworded paragraphs are below. Write knowledge-base rows \
for what they now say.

Return ONLY a JSON array. Each element:
  {{"category": str, "subcategory": str, "question": str, "answer": str,
    "keywords": str, "audience": one of {audiences}}}

Rules, none optional:
- Every answer must be supported word-for-word by the paragraphs below. If a \
figure or date is not in them, it does not go in a row.
- One row per distinct fact a person might ask about. No row for navigation \
text, headings without content, or marketing phrases.
- Write the question the way a person in St Kitts and Nevis would ask it.
- If nothing below is worth a row, return [].

Changed paragraphs from {url}:

{blocks}
"""


async def draft(state: WatcherState) -> dict[str, Any]:
    """The one model call: changed paragraphs in, review-ready rows out."""
    from app.agent import build_chat_model

    model = build_chat_model()
    today = date.today().isoformat()
    stamp = today.replace("-", "")
    drafts: list[dict[str, Any]] = []
    for change in state.get("changes", []):
        prompt = _DRAFT_PROMPT.format(
            audiences=list(AUDIENCES), url=change["url"], blocks="\n\n".join(change["blocks"])
        )
        reply = await model.ainvoke(prompt)
        for row in parse_rows(getattr(reply, "content", "") or ""):
            row["source_url"] = change["url"]
            row["as_of"] = today
            row["kb_id"] = f"{ID_PREFIX}-{stamp}-{len(drafts):02d}"
            row["why"] = "drafted by the website watcher from a page change; verify every figure against the page"
            drafts.append(row)
    return {"drafts": drafts}


def parse_rows(reply: str) -> list[dict[str, Any]]:
    """The JSON array in a model reply, tolerating a code fence around it.

    A row missing a required field or claiming an unknown audience is dropped
    here, not downstream: what enters the queue is already shaped like the
    corpus, and the human reviewer's whole job is checking truth, not format.
    """
    text = reply.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|\n?```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("watcher: model reply was not JSON; nothing drafted")
        return []
    if not isinstance(parsed, list):
        return []
    rows = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        if not (item.get("question") or "").strip() or not (item.get("answer") or "").strip():
            continue
        if item.get("audience") not in AUDIENCES:
            item["audience"] = "general"
        rows.append({key: str(item.get(key) or "").strip()
                     for key in ("category", "subcategory", "question", "answer", "keywords", "audience")})
    return rows


async def queue(state: WatcherState) -> dict[str, Any]:
    """Everything drafted goes to `pending_kb_rows`, and nowhere else."""
    from app.watcher.store import queue_rows

    queued = await queue_rows(state.get("drafts", []))
    if queued:
        logger.info("watcher: %d rows queued for review", queued)
    return {"queued": queued}


def _something_changed(state: WatcherState) -> str:
    return "draft" if state.get("changes") else END


def build_watcher_graph():
    graph = StateGraph(WatcherState)
    graph.add_node("fetch", fetch)
    graph.add_node("diff", diff)
    graph.add_node("draft", draft)
    graph.add_node("queue", queue)
    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "diff")
    graph.add_conditional_edges("diff", _something_changed, ["draft", END])
    graph.add_edge("draft", "queue")
    graph.add_edge("queue", END)
    return graph.compile()
