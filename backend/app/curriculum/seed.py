"""Loading the authored curriculum into Postgres."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


#: The bands a concept body is written for, weakest first.
_BANDS: tuple[str, ...] = ("5-8", "9-12", "13-15", "16-18", "adult")

#: Which column holds each band's body.
_BODY_COLUMN: dict[str, str] = {
    "5-8": "body_5_8",
    "9-12": "body_9_12",
    "13-15": "body_13_15",
    "16-18": "body_16_18",
    "adult": "body_adult",
}


def _for_band(mapping: Any, band: str) -> list[str]:
    """This band's entries, inheriting downward exactly as `for_band` does."""
    if not isinstance(mapping, dict):
        return []
    if band not in _BANDS:
        return []
    for step in range(_BANDS.index(band), -1, -1):
        got = mapping.get(_BANDS[step])
        if got:
            return list(got) if isinstance(got, (list, tuple)) else [str(got)]
    return []


def teaching_payload(lessons: list[Any]) -> dict[str, Any]:
    """A concept's teachable content, composed from the lessons that teach it.

    THE CONCEPT ROWS WERE SHELLS. This function is why the seeder writes more
    than eight columns now.

    `TeachingConcept.teachable_at` ends on `body_for(band) is not None`, so a
    concept with no body cannot be taught to anybody. The seeder wrote id,
    slug, title, name, bands, module and vocabulary -- and no body, no checks,
    nothing to say. Measured on production, 27 Aug: six concept rows loaded and
    `concepts_teachable` was zero at every band. The tutor could never claim a
    turn, so "how does saving work?" fell through to the lesson machine and
    came back as a check question about something nobody had asked. Every
    persona, every band, every time.

    The content to fix it was already here. `teach_points` and `examples` are
    written per band in the curriculum, and so are the check prompts and their
    hint ladders. This composes them rather than inventing anything: the words
    a reader hears are the words the curriculum author wrote for that band.
    """
    payload: dict[str, Any] = {column: None for column in _BODY_COLUMN.values()}
    payload["local_example"] = ""
    checks: list[dict[str, Any]] = []

    for band in _BANDS:
        points: list[str] = []
        examples: list[str] = []
        for lesson in lessons:
            points.extend(_for_band(getattr(lesson, "teach_points", None), band))
            examples.extend(_for_band(getattr(lesson, "examples", None), band))
        if not points:
            continue
        body = " ".join(str(p).strip() for p in points if str(p).strip())
        if examples:
            body = f"{body} For example: {str(examples[0]).strip()}"
        payload[_BODY_COLUMN[band]] = body
        if band == "9-12" and examples:
            payload["local_example"] = str(examples[0]).strip()

        # The authored check for this band, with its hint ladder intact.
        for lesson in lessons:
            for question in getattr(lesson, "check_questions", ()) or ():
                prompt = _for_band(getattr(question, "prompt", None), band)
                if not prompt:
                    continue
                options = list(getattr(question, "options", ()) or ())
                index = getattr(question, "answer", 0)
                answer = ""
                if isinstance(index, int) and 0 <= index < len(options):
                    answer = str(options[index])
                checks.append(
                    {
                        "id": f"{getattr(question, 'id', 'chk')}::{band}",
                        "band": band.replace("-", "_"),
                        "type": "mcq" if options else "short_answer",
                        "question": str(prompt[0]),
                        "answer": answer,
                        "accept": [str(a) for a in (getattr(question, "accept", ()) or ())],
                        "hints": [str(h) for h in _for_band(getattr(question, "hints", None), band)],
                    }
                )

    payload["check_bank"] = checks
    return payload


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
    # Which lessons teach each concept, so a concept can be given words to say.
    by_concept: dict[str, list[Any]] = {}
    for lesson in getattr(curriculum, "lessons", {}).values():
        by_concept.setdefault(getattr(lesson, "concept_id", ""), []).append(lesson)
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
                    teaching = teaching_payload(by_concept.get(concept.id, []))
                    await db.execute(
                        sql(
                            """
                            INSERT INTO concepts (
                                id, slug, title,
                                name, band_min, band_max, module_id, vocabulary,
                                body_5_8, body_9_12, body_13_15, body_16_18,
                                body_adult, local_example, check_bank, status
                            ) VALUES (
                                :id, :slug, :title,
                                :name, :band_min, :band_max, :module, :vocabulary,
                                :body_5_8, :body_9_12, :body_13_15, :body_16_18,
                                :body_adult, :local_example, CAST(:check_bank AS jsonb),
                                :status
                            )
                            ON CONFLICT (id) DO UPDATE SET
                                title = EXCLUDED.title,
                                name = EXCLUDED.name,
                                band_min = EXCLUDED.band_min,
                                band_max = EXCLUDED.band_max,
                                module_id = EXCLUDED.module_id,
                                vocabulary = EXCLUDED.vocabulary,
                                body_5_8 = EXCLUDED.body_5_8,
                                body_9_12 = EXCLUDED.body_9_12,
                                body_13_15 = EXCLUDED.body_13_15,
                                body_16_18 = EXCLUDED.body_16_18,
                                body_adult = EXCLUDED.body_adult,
                                local_example = EXCLUDED.local_example,
                                check_bank = EXCLUDED.check_bank,
                                status = EXCLUDED.status
                            """
                        ),
                        {
                            "id": concept.id,
                            # `slug` and `title` are NOT NULL since 0016; id and name fill them.
                            "slug": concept.id,
                            "title": concept.name,
                            "name": concept.name,
                            "band_min": concept.band_min,
                            "band_max": concept.band_max,
                            "module": module.id,
                            "vocabulary": list(concept.vocabulary),
                            "body_5_8": teaching["body_5_8"],
                            "body_9_12": teaching["body_9_12"],
                            "body_13_15": teaching["body_13_15"],
                            "body_16_18": teaching["body_16_18"],
                            "body_adult": teaching["body_adult"],
                            "local_example": teaching["local_example"],
                            "check_bank": json.dumps(teaching["check_bank"]),
                            # `SERVABLE_STATUSES` accepts draft, but say what
                            # this is: authored material, reviewed by the
                            # client, not a machine's guess.
                            "status": "approved",
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
