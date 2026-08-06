"""Delete cached answers and semantic shelves; keep the embedding cache.

Measurement tooling for the latency probes: a warm-MISS run needs every answer
to miss while the embedding cache stays warm, because that is the steady state
a first-time question actually experiences.

    python -m scripts.flush_probe_answers
"""

import asyncio

from app.cache import _FLUSH_PREFIXES, get_client, namespace

#: Answers and shelves, every version -- but never the embedding cache, which is
#: the whole point of this script as opposed to `flush_answers()`.
#:
#: Derived from the canonical list rather than spelled out again. Both copies had
#: gone stale at `answer:v1:` after the age band bumped the key to v2, and here
#: that is worse than a missed reclaim: a warm-MISS probe that silently deletes
#: nothing measures warm HITS and reports them under the other name.
_PREFIXES = tuple(p for p in _FLUSH_PREFIXES if not p.startswith("embed:"))


async def main() -> None:
    client = get_client()
    if client is None:
        print("no Valkey configured")
        return
    deleted = 0
    for prefix in _PREFIXES:
        async for key in client.scan_iter(match=f"{namespace()}{prefix}*", count=200):
            await client.delete(key)
            deleted += 1
    print(f"deleted {deleted} answer/shelf keys; embedding cache untouched")


if __name__ == "__main__":
    asyncio.run(main())
