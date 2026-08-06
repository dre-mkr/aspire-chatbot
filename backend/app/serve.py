"""Run the API. Use this rather than `python -m uvicorn app.main:app`.

    python -m app.serve                 # 127.0.0.1:8000
    python -m app.serve --port 8011
    HOST=0.0.0.0 PORT=8080 python -m app.serve

On Linux this is `uvicorn.run` with the arguments spelled out, and nothing else.
On Windows it is the difference between having conversation persistence and
silently not having it.

## Why this module exists

psycopg's async mode cannot run on Windows' `ProactorEventLoop`, and the
checkpointer is psycopg. uvicorn 0.52 selects the loop like this:

    # uvicorn/server.py
    asyncio_run(self.serve(), loop_factory=self.config.get_loop_factory())

    # uvicorn/loops/asyncio.py
    if sys.platform == "win32" and not use_subprocess:
        return asyncio.ProactorEventLoop

`use_subprocess` is only true under `--reload` or `--workers > 1`, so the
ordinary single-worker dev command gets a Proactor loop. And because that is an
explicit `loop_factory`, `asyncio.set_event_loop_policy(...)` cannot override
it -- a policy only applies to loops created through the policy. So
`install_windows_event_loop_policy()`, called at import in `app/main.py`, is
inert here however early it runs. It was the fix, it looked like the fix, and
it never applied to the loop uvicorn actually used.

The symptom was not an error anybody would connect to the loop: a 30-second
`PoolTimeout`, logged as "the checkpointer could not open a connection pool",
after which the graph runs with NO checkpointer at all. Every turn starts from
a fresh state, nothing resumes, and the answers still look right -- so it reads
as a slow database rather than as a product with no memory.

Supplying the loop factory here is the fix, because it is the only place that
gets to choose before the loop exists. Production is Linux and takes the plain
path; `python -m uvicorn app.main:app` still works there and always did.
"""

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
        # The reloader supervises a child process and never runs the app on
        # this loop, so choosing one here would apply to the wrong process.
        uvicorn.Server(config).run()
        return

    server = uvicorn.Server(config)
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=_selector_loop)
    else:
        server.run()


if __name__ == "__main__":
    main()
