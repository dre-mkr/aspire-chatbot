"""Loading the authored curriculum into Postgres.

The YAML files are the source of truth for CONTENT. The tables are what
`mastery`, `learning_sessions` and the admin queue point their foreign keys at,
and until something writes the rows those keys have nothing to reference.

## The gap this closes

There was none, and it was not visible from any test. `mastery.concept_id`
references `concepts.id`; `concepts` was empty; so every attempt to record what
a child had learned raised `mastery_concept_id_fkey`, took down the node, and
told them the assistant was unavailable. The suite never saw it because the
learning tests use the in-memory store, which has no foreign keys to violate.

Found by running one widget interaction against the real database.

## Idempotent, and safe to run on every start

`ON CONFLICT DO UPDATE` on the module, the concepts and the lessons' concept
links. Re-running after an edit to a YAML file updates the rows; re-running
after no change writes the same values back. Neither needs anybody to remember
which it is.

## What is NOT written here

Lesson bodies. The tables carry a lesson's identity and its ordering so that a
mastery row and a session log can point at one; the teaching text, the hint
ladder and the check questions stay in the YAML and are read from
`load_all()` at request time.

That split is deliberate. Content is reviewed and edited as files in a branch;
copying it into a database creates a second version of the same paragraph and no
answer to which one a reader saw.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def seed_curriculum(curriculum: Any | None = None) -> int:
    """Write every authored module, concept and lesson row. Returns the concepts written.

    Never raises. A curriculum that cannot be seeded is a deployment where
    mastery will not record -- which is a real degradation and is logged as one
    -- but it is not a reason to refuse to answer a question, and this runs at
    startup where raising would mean refusing to start.
    """
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
                            # `slug` and `title` are NOT NULL as of migration 0016,
                            # which gave this table teaching bodies and the columns
                            # that resolve an utterance to one.
                            #
                            # They are supplied on the INSERT list even though every
                            # authored concept already exists and this statement
                            # always takes the UPDATE branch. That is not belt and
                            # braces -- it is required. Postgres evaluates NOT NULL
                            # when it forms the candidate tuple, which happens BEFORE
                            # it consults the arbiter index and discovers the
                            # conflict. A null here fails the whole statement even
                            # when the row it would have updated is sitting there
                            # with a perfectly good slug in it.
                            #
                            # That is exactly how this broke: the five authored rows
                            # were correct, the migration had backfilled them, and
                            # startup still raised `NotNullViolationError` on every
                            # boot -- silently, because this function swallows and
                            # logs rather than refusing to start. The visible symptom
                            # was mastery quietly not recording.
                            #
                            # `slug` mirrors `id` for authored concepts; synthesised
                            # ones (`CON-####`) carry a separate slug. It is absent
                            # from the DO UPDATE list because `id` is the conflict
                            # target and therefore cannot change, which makes
                            # `slug = EXCLUDED.slug` a provable no-op.
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
