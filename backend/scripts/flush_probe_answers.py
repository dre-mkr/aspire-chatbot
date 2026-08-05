"""Delete cached answers and semantic shelves; keep the embedding cache.

Measurement tooling for the latency probes: a warm-MISS run needs every answer
to miss while the embedding cache stays warm, because that is the steady state
a first-time question actually experiences.

    python -m scripts.flush_probe_answers
"""

import asyncio

from app.cache import get_client, namespace


async def main() -> None:
    client = get_client()
    if client is None:
        print("no Valkey configured")
        return
    deleted = 0
    for prefix in ("answer:v1:", "semindex:v1:"):
        async for key in client.scan_iter(match=f"{namespace()}{prefix}*", count=200):
            await client.delete(key)
            deleted += 1
    print(f"deleted {deleted} answer/shelf keys; embedding cache untouched")


if __name__ == "__main__":
    asyncio.run(main())
