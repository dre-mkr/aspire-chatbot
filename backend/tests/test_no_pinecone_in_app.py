"""Pinecone is a tool on the workbench. It is not a part in the engine.

`tools/research_to_kb.py` turns research PDFs into knowledge-base rows offline,
and the rows it produces reach readers the same way every other row does: a
person approves them, they are appended to `data/knowledge_base.csv`, and the
existing ingest embeds them. The live retriever -- pgvector, BM25, RRF fusion,
the cross-encoder -- never learns Pinecone exists.

That boundary is one import away from being untrue, so it is checked here
rather than remembered. `evals/grounding.jsonl` is calibrated against that exact
chain and `qa_relevance_floor` is set at 0.55 for it; change the store and every
one of those numbers is unverified.

The scan is static -- `ast`, not `importlib` -- so it holds for a module that
cannot be imported in a test environment, and it cannot be satisfied by a
package simply being absent from the venv.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path("app")
TOOLS = Path("tools")

#: Anything whose top-level package is one of these.
FORBIDDEN: frozenset[str] = frozenset({"pinecone", "pinecone_plugins"})

MODULES: list[Path] = sorted(APP.rglob("*.py"))


def imported_packages(path: Path) -> set[str]:
    """Every top-level package `path` imports, however it spells the import."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # `level` non-zero is a relative import, which cannot reach a
            # third-party package.
            if node.module and not node.level:
                found.add(node.module.split(".")[0])
    return found


class TestNothingUnderAppImportsPinecone:
    @pytest.mark.parametrize("path", MODULES, ids=lambda path: str(path).replace("\\", "/"))
    def test_the_module_stays_on_this_side_of_the_boundary(self, path):
        assert not (imported_packages(path) & FORBIDDEN)

    def test_the_scan_walked_a_real_package(self):
        """A scanner pointed at nothing passes forever.

        The direction of this assertion is the point. `pinecone` appears nowhere
        under `app/`, so the test above is green whether the walk found two
        hundred modules or zero, and a wrong root path would never say so.
        """
        assert len(MODULES) > 50
        assert APP / "graph" / "main_graph.py" in MODULES

    def test_the_scan_catches_a_planted_import(self, tmp_path):
        """The other half of the control: prove it fails when it should."""
        planted = tmp_path / "planted.py"
        planted.write_text("from pinecone import Pinecone\n", encoding="utf-8")
        assert imported_packages(planted) & FORBIDDEN

        planted.write_text("import pinecone.grpc as grpc\n", encoding="utf-8")
        assert imported_packages(planted) & FORBIDDEN

        planted.write_text("from pinecone_plugins.assistant.models.chat import Message\n",
                           encoding="utf-8")
        assert imported_packages(planted) & FORBIDDEN

    def test_an_ordinary_import_is_not_flagged(self, tmp_path):
        planted = tmp_path / "ordinary.py"
        planted.write_text("from app.graph.state import AspireState\nimport re\n", encoding="utf-8")
        assert not (imported_packages(planted) & FORBIDDEN)


class TestTheToolIsWhereThePineconeImportsLive:
    """The tool exists, it is outside `app/`, and it only reaches for Pinecone lazily."""

    def test_the_tool_is_not_under_app(self):
        script = TOOLS / "research_to_kb.py"
        assert script.is_file()
        assert APP not in script.parents

    def test_no_module_under_app_imports_the_tool(self):
        for path in MODULES:
            assert "research_to_kb" not in path.read_text(encoding="utf-8")

    def test_the_tool_imports_pinecone_inside_a_function_not_at_module_scope(self):
        """So `--append`, which touches this repo's data, runs without the package."""
        tree = ast.parse((TOOLS / "research_to_kb.py").read_text(encoding="utf-8"))
        top_level: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                top_level.add(node.module.split(".")[0])
        assert not (top_level & FORBIDDEN)

    def test_the_tool_does_not_import_the_application(self):
        """A dev tool that imports `app/` drags the whole runtime into a dev run."""
        assert "app" not in imported_packages(TOOLS / "research_to_kb.py")

    def test_pinecone_is_declared_dev_only(self):
        dev = Path("requirements-dev.txt").read_text(encoding="utf-8")
        runtime = Path("requirements.txt").read_text(encoding="utf-8")
        assert "pinecone" in dev and "pinecone-plugin-assistant" in dev
        assert "pinecone" not in runtime.lower()
