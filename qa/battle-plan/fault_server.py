"""The backend with one dependency deliberately broken — AGT-09, AGT-10, PRF-07.

The plan asks for these "with engineering's help", because you cannot test how a
system fails without making it fail. This is that help, in one file: it imports
the real application and replaces exactly one seam before uvicorn starts.

    python fault_server.py retrieval-down   # both retrievers raise
    python fault_server.py retrieval-slow   # retrieval takes 12 seconds
    python fault_server.py backend-500      # every chat turn raises inside the graph

Nothing in `backend/` is edited. Run it on 8002 and point a track at it.
"""

from __future__ import annotations

import asyncio
import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "backend")
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

MODE = (sys.argv[1] if len(sys.argv) > 1 else "retrieval-down").strip()
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8002


class ToolDown(RuntimeError):
    """What a dependency looks like when it is not there."""


def _patch() -> None:
    import app.agents.qa.graph as qa_graph

    real_search = qa_graph._search
    real_corpus = qa_graph._corpus

    async def dead_search(query: str, k: int):
        raise ToolDown("the vector store is unreachable")

    async def dead_corpus(audience: str):
        raise ToolDown("the corpus table is unreachable")

    async def slow_search(query: str, k: int):
        await asyncio.sleep(12)
        return await real_search(query, k)

    async def slow_corpus(audience: str):
        await asyncio.sleep(12)
        return await real_corpus(audience)

    if MODE == "retrieval-down":
        qa_graph._search = dead_search
        qa_graph._corpus = dead_corpus
    elif MODE == "retrieval-slow":
        qa_graph._search = slow_search
        qa_graph._corpus = slow_corpus
    elif MODE == "backend-500":
        import app.graph.main_graph as main_graph
        real_build = main_graph.build_main_graph

        def exploding_build(*args, **kwargs):
            raise ToolDown("simulated backend failure inside the graph")

        main_graph.build_main_graph = exploding_build
        _ = real_build
    else:
        raise SystemExit(f"unknown mode {MODE!r}")

    print(f"[fault-server] mode={MODE} port={PORT}", flush=True)


def main() -> None:
    _patch()
    import uvicorn
    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
