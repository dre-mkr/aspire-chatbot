"""Run the API."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys


def _selector_loop() -> asyncio.AbstractEventLoop:
    """A loop psycopg can connect on. Windows only; see the module docstring."""
    return asyncio.SelectorEventLoop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.serve", description=__doc__)
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument(
        "--reload",
        action="store_true",
        help="uvicorn's reloader. Runs in a subprocess, which already gets a "
        "Selector loop on Windows, so this module changes nothing there.",
    )
    args = parser.parse_args(argv)

    import uvicorn

    config = uvicorn.Config(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=1,
    )

    if args.reload:
        # The reloader only supervises a child process, so the loop chosen here would never serve.
        uvicorn.Server(config).run()
        return

    server = uvicorn.Server(config)
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=_selector_loop)
    else:
        server.run()


if __name__ == "__main__":
    main()
