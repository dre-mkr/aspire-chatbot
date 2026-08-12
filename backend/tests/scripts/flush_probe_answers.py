"""Delete cached answers and semantic shelves; keep the embedding cache."""

import asyncio

from app.cache import _FLUSH_PREFIXES, get_client, namespace

#: Answers and shelves, every version -- but never the embedding cache.
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
