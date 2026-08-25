"""The watcher: text extraction, diffing, drafting, and the review-only exit.

Everything here runs hermetically -- no database, no network, no model. The
store and the chat model are the two edges, and both are monkeypatched, which
is exactly why `graph.py` reaches for them with late imports.
"""

from __future__ import annotations

import asyncio
import csv
from types import SimpleNamespace

import pytest

import app.watcher.store as store
from app.watcher import graph as watcher
from app.watcher.__main__ import REVIEW_COLUMNS, _export


# ── page_text ────────────────────────────────────────────────────────────────


def test_page_text_keeps_words_and_drops_machinery():
    html = """
    <html><head><title>x</title><style>p{color:red}</style></head>
    <body><script>alert(1)</script>
    <h2>Eligibility</h2>
    <p>Children aged 5 to 18 who are citizens of St Kitts and Nevis.</p>
    </body></html>
    """
    text = watcher.page_text(html)
    assert "Children aged 5 to 18" in text
    assert "alert" not in text
    assert "color:red" not in text


# ── changed_blocks ───────────────────────────────────────────────────────────


OLD = "\n".join([
    "The ASPIRE Programme gives every eligible child a financial start today.",
    "Enrolment for the first cohort begins in September of this year, 2026.",
])


def test_identical_pages_change_nothing():
    assert watcher.changed_blocks(OLD, OLD) == []


def test_a_new_paragraph_is_reported_and_a_deleted_one_is_not():
    new = OLD.split("\n")[0] + "\nDeposits above the initial EC$1,000 can be made at any branch office."
    blocks = watcher.changed_blocks(OLD, new)
    assert blocks == ["Deposits above the initial EC$1,000 can be made at any branch office."]


def test_short_fragments_do_not_become_review_work():
    assert watcher.changed_blocks(OLD, OLD + "\nRead more") == []


# ── parse_rows ───────────────────────────────────────────────────────────────


def test_parse_rows_tolerates_a_code_fence_and_bad_audiences():
    reply = """```json
    [{"category": "programme", "subcategory": "deposits", "question": "Can I add money?",
      "answer": "Yes, at any branch.", "keywords": "deposit", "audience": "everyone"},
     {"category": "x", "question": "No answer here", "answer": "", "audience": "general"}]
    ```"""
    rows = watcher.parse_rows(reply)
    assert len(rows) == 1
    assert rows[0]["audience"] == "general"  # unknown vocabulary is coerced, not invented


def test_parse_rows_survives_a_model_that_did_not_return_json():
    assert watcher.parse_rows("I'm sorry, here are some thoughts...") == []


# ── the graph, end to end, with both edges faked ────────────────────────────


class _FakeModel:
    def __init__(self, content: str) -> None:
        self._content = content

    async def ainvoke(self, prompt: str):
        return SimpleNamespace(content=self._content)


def test_first_visit_baselines_and_never_drafts(monkeypatch):
    saved = {}

    async def no_snapshot(url):
        return None

    async def save(url, content_hash, content):
        saved[url] = content_hash

    monkeypatch.setattr(store, "load_snapshot", no_snapshot)
    monkeypatch.setattr(store, "save_snapshot", save)

    state = {"pages": [{"url": "https://aspire.gov.kn/", "text": OLD, "hash": watcher.text_hash(OLD)}]}
    result = asyncio.run(watcher.diff(state))
    assert result["baselined"] == 1
    assert result["changes"] == []
    assert "https://aspire.gov.kn/" in saved
    assert watcher._something_changed(result) != "draft"


def test_a_changed_page_flows_to_the_queue_marked_for_review(monkeypatch):
    new_text = OLD + "\nWithdrawals are permitted once the participant reaches eighteen years of age."

    async def old_snapshot(url):
        return SimpleNamespace(content=OLD, content_hash=watcher.text_hash(OLD))

    async def save(url, content_hash, content):
        pass

    queued = []

    async def capture(drafts):
        queued.extend(drafts)
        return len(drafts)

    monkeypatch.setattr(store, "load_snapshot", old_snapshot)
    monkeypatch.setattr(store, "save_snapshot", save)
    monkeypatch.setattr(store, "queue_rows", capture)

    import app.agent as agent_module
    monkeypatch.setattr(agent_module, "build_chat_model", lambda *a, **k: _FakeModel(
        '[{"category":"programme","subcategory":"withdrawals",'
        '"question":"When can I withdraw?","answer":"At eighteen.",'
        '"keywords":"withdraw","audience":"student"}]'
    ))

    state = {"pages": [{"url": "https://aspire.gov.kn/", "text": new_text, "hash": watcher.text_hash(new_text)}]}
    diffed = asyncio.run(watcher.diff(state))
    assert watcher._something_changed(diffed) == "draft"

    drafted = asyncio.run(watcher.draft(diffed))
    result = asyncio.run(watcher.queue(drafted))

    assert result["queued"] == 1
    row = queued[0]
    assert row["kb_id"].startswith("WEB-")            # never ASP-: the append gate must not mistake it
    assert row["source_url"] == "https://aspire.gov.kn/"
    assert row["audience"] == "student"


# ── export: every row leaves marked needs_review=yes ─────────────────────────


def test_export_writes_the_review_csv_the_append_gate_expects(monkeypatch, tmp_path):
    pending = [SimpleNamespace(
        kb_id="WEB-20260824-00", category="programme", subcategory="deposits",
        question="Can I add money?", answer="Yes, at any branch.", keywords="deposit",
        audience="general", source_url="https://aspire.gov.kn/", as_of="2026-08-24",
        why="drafted by the website watcher",
    )]

    async def rows():
        return pending

    exported = []

    async def mark(ids):
        exported.extend(ids)
        return len(ids)

    monkeypatch.setattr(store, "pending_rows", rows)
    monkeypatch.setattr(store, "mark_exported", mark)

    out = tmp_path / "website.csv"
    assert asyncio.run(_export(out)) == 0

    with out.open(encoding="utf-8", newline="") as handle:
        written = list(csv.DictReader(handle))
    assert tuple(written[0].keys()) == REVIEW_COLUMNS
    assert written[0]["needs_review"] == "yes"        # the watcher cannot approve its own work
    assert exported == ["WEB-20260824-00"]
