#!/usr/bin/env bash
# S1-007 — the same eligibility question retrieves in English and retrieves
# NOTHING in Spanish and French.
#
# ASP-031 is the eligibility cut-off row:
#   "Eligibility covers young people who are currently aged 5 to 18, as well as
#    those who were 18 or under on 13 December 2023..."
#
# SAFETY: scratch container only. Costs 3 query embeddings (~$0.00002).
#
#   bash bug-hunt/repro/S1-007-crosslingual-eligibility.sh
set -u
cd "$(dirname "$0")/../../backend" || exit 1

DATABASE_URL="postgresql://bughunt:bughunt@127.0.0.1:55433/aspire_bughunt" \
SESSION_SECRET="bughunt-scratch-secret-not-production-32bytes" \
VALKEY_URL="redis://127.0.0.1:6380/9" \
ASPIRE_CACHE_NAMESPACE="bughunt-" \
.venv/Scripts/python.exe - <<'PY'
import asyncio
from sqlalchemy import text
from app.config import get_settings
from app.db import session
from app.rag import build_embeddings

QUESTIONS = [
    ("en", "What does the 13 December 2023 date mean for eligibility?"),
    ("es", "¿Qué significa la fecha del 13 de diciembre de 2023?"),
    ("fr", "Que signifie la date du 13 décembre 2023 ?"),
]
TARGET = "ASP-031"

async def main():
    from app.rag import chroma_floor_as_cosine_distance
    s = get_settings()
    raw = s.retriever_score_threshold
    # The configured 0.2 is a CHROMA RELEVANCE floor; rag.py translates it to a
    # cosine-distance cutoff. The effective similarity gate is what matters.
    cos_cut = chroma_floor_as_cosine_distance(raw)
    floor = 1.0 - cos_cut if cos_cut is not None else 0.0
    print(f"RETRIEVER_SCORE_THRESHOLD={raw}  ->  effective similarity floor = {floor:.6f}")
    print(f"target row = {TARGET} (the eligibility cut-off)\n")
    emb = build_embeddings()
    async with session() as db:
        for lang, q in QUESTIONS:
            v = emb.embed_query(q)
            vec = "[" + ",".join(repr(float(x)) for x in v) + "]"
            rows = (await db.execute(text(
                "SELECT kb_id, 1 - (embedding <=> CAST(:v AS vector)) AS similarity "
                "FROM documents WHERE language='en' "
                "ORDER BY embedding <=> CAST(:v AS vector) LIMIT 3"
            ), {"v": vec})).fetchall()
            best = rows[0] if rows else None
            target = next((r for r in rows if r[0] == TARGET), None)
            print(f"[{lang}] {q}")
            for kb_id, sim in rows:
                mark = "  <-- TARGET" if kb_id == TARGET else ""
                gate = "PASS" if sim >= floor else "cut"
                print(f"      {kb_id:10} similarity={sim:.4f}  [{gate}]{mark}")
            above = [r for r in rows if r[1] >= floor]
            print(f"      => {len(above)} of top-3 survive the {floor} floor"
                  f"{'  ** NOTHING RETRIEVED **' if not above else ''}\n")

asyncio.run(main())
PY
