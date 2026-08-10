"""Loading the authored curriculum into Postgres."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def seed_curriculum(curriculum: Any | None = None) -> int:
    """Write every authored module, concept and lesson row."""
    from app.db import database_enabled

    if not database_enabled():
        return 0

    if curriculum is None:
        from app.curriculum.schema import load_all

        try:
            curriculum = load_all()
        except Exception:
            logger.error(
                "The authored curriculum could not be loaded, so mastery has no "
                "concepts to reference and will not record.",
                exc_info=True,
            )
            return 0

    from sqlalchemy import text as sql

    from app.db import session

    written = 0
    try:
        async with session() as db:
            if db is None:
                return 0
            for module in curriculum.modules:
                await db.execute(
                    sql(
                        """
                        INSERT INTO modules (id, title, order_index, band_min, band_max)
                        VALUES (:id, :title, :order, :band_min, :band_max)
                        ON CONFLICT (id) DO UPDATE SET
                            title = EXCLUDED.title,
                            order_index = EXCLUDED.order_index,
                            band_min = EXCLUDED.band_min,
                            band_max = EXCLUDED.band_max,
                            updated_at = now()
                        """
                    ),
                    {
                        "id": module.id,
                        "title": module.title,
                        "order": module.order,
                        "band_min": module.band_min,
                        "band_max": module.band_max,
                    },
                )

                for concept in module.concepts:
                    await db.execute(
                        sql(
                            """
                            INSERT INTO concepts (
                                id, slug, title,
                                name, band_min, band_max, module_id, vocabulary
                            ) VALUES (
                                :id, :slug, :title,
                                :name, :band_min, :band_max, :module, :vocabulary
                            )
                            ON CONFLICT (id) DO UPDATE SET
                                title = EXCLUDED.title,
                                name = EXCLUDED.name,
                                band_min = EXCLUDED.band_min,
                                band_max = EXCLUDED.band_max,
                                module_id = EXCLUDED.module_id,
                                vocabulary = EXCLUDED.vocabulary
                            """
                        ),
                        {
                            "id": concept.id,
                            # `slug` and `title` are NOT NULL as of migration 0016, which gave this table teaching bodies and the columns t…
                            "slug": concept.id,
                            "title": concept.name,
                            "name": concept.name,
                            "band_min": concept.band_min,
                            "band_max": concept.band_max,
                            "module": module.id,
                            "vocabulary": list(concept.vocabulary),
                        },
                    )
                    written += 1

            await db.commit()
    except Exception:
        logger.error(
            "Seeding the curriculum failed, so mastery has no concepts to "
            "reference and will not record.",
            exc_info=True,
        )
        return 0

    logger.info("Curriculum seeded: %d concepts.", written)
    return written


def main() -> int:
    """`python -m app.curriculum.seed`, for a deployment that seeds explicitly."""
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    count = asyncio.run(seed_curriculum())
    print(f"{count} concepts written.")
    return 0 if count else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
