# Database target confirmation — read before trusting any write-path finding

Recorded 2026-08-05, before any test that writes.

## What the repo is configured for (NOT USED FOR TESTING)

`backend/.env` ships with:

```
DATABASE_URL: postgresql://***:***@ep-wispy-wave-ayny4onp-pooler.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require
VALKEY_URL:   redis://localhost:6380
```

That is a live Neon endpoint. **No test in this bug hunt writes to it.** It was
read exactly once, to identify it, with credentials masked in the output.

## What testing actually runs against

A dedicated container, created for this hunt and disposable:

```
container:     aspire-bughunt-pg
image:         pgvector/pgvector:pg16
DATABASE_URL:  postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt
```

Verified:

```
$ docker exec aspire-bughunt-pg psql -U bughunt -d aspire_bughunt \
    -c "SELECT current_database(), inet_server_port();"
 current_database | inet_server_port
------------------+------------------
 aspire_bughunt   |

$ ... -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT extname, extversion ..."
 extname | extversion
---------+------------
 vector  | 0.8.6

$ DATABASE_URL=... python -c "app.config.get_settings().database_url"
Settings sees DATABASE_URL host: postgresql://***@127.0.0.1:55433/aspire_bughunt
```

## Cache isolation

The host's Valkey on :6380 is **shared with an unrelated application**
(`caribpay-redis-1`, BullMQ queues) — this was already on the record as P7-002.
Testing therefore uses:

```
VALKEY_URL=redis://127.0.0.1:6380/9      # db index 9, not the default 0
ASPIRE_CACHE_NAMESPACE=bughunt-          # key prefix isolation on top
```

Both are belt-and-braces: the index separates the keyspace, the namespace
separates the keys within it.

## Teardown

```
docker rm -f aspire-bughunt-pg
redis-cli -p 6380 -n 9 FLUSHDB
```

## Standing rule for this hunt

Every command in `repro/` sets `DATABASE_URL` explicitly. None of them inherit
it from `backend/.env`. If a repro script does not set it, that is a bug in the
script and it must not be run.
