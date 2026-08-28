"""The eleven authored topics, turned into concepts the tutor can teach.

`module_01_saving.yaml` teaches six concepts, all of them savings-adjacent.
The eleven topics are the rest of the curriculum: interest, credit, investing,
taxes, scams, digital money, entrepreneurship, and what AI does with a
reader's own money. Each was written for seven voices, band by band, with the
vocabulary gates reasoned through in the file itself -- `interest` is banned
at 5-8, `loan` waits until 13-15, and the 5-8 version of budgeting teaches the
idea without the noun.

NOTHING HERE IS INVENTED. The body a reader hears is the author's own copy for
their band, and the check they are asked is the question the author closed
that cell with. Where a cell has no copy -- Skye on credit, Skye on investing
-- no body is written and the concept is simply not teachable at that band,
which is what the gate intended.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONTENT = Path(__file__).parent / "content" / "topics_eleven.json"

#: Which band each authored voice was written for.
#:
#: `imani` and `azuri` are both adult, and `guest` is an unknown adult. Imani
#: carries the adult band because she is written for a reader being told about
#: their own money; Azuri is written for a professional preparing a lesson,
#: which is a different job from being taught.
_VOICE_BAND: dict[str, str] = {
    "skye": "5-8",
    "kaleb": "9-12",
    "z13": "13-15",
    "z16": "16-18",
    "imani": "adult",
}

_BAND_ORDER: tuple[str, ...] = ("5-8", "9-12", "13-15", "16-18", "adult")

#: Topics that are another name for a concept the module already teaches.
#:
#: These ENRICH rather than duplicate: the eleven-topic copy is written for
#: bands the module's own lessons do not reach, so the two together cover more
#: than either alone. A second `saving` concept would split a reader's mastery
#: across two ids for one idea.
_EXISTING: dict[str, str] = {
    "what is budgeting": "budget",
    "what is saving": "save",
    "what are needs vs wants": "need",
}


#: Short, stable ids for the topics whose titles make an unwieldy slug.
#:
#: A concept id shows up in logs, in mastery rows and in a reader's journey, so
#: it is worth naming rather than deriving.
_ID: dict[str, str] = {
    "how does ai help you with budgeting planning and saving": "ai_money",
    "mobile money and digital banking": "mobile_money",
    "scams and staying safe": "scams",
}


def _slug(title: str) -> str:
    """A stable id from a title, without the question mark and the filler."""
    text = title.strip().lower()
    text = re.sub(r"^(what is|what are|how does|how do)\s+", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:48] or "topic"


def _split_check(copy: list[str]) -> tuple[list[str], str]:
    """The teaching lines, and the question the author closed with.

    A closing question is a check the author wrote. Leaving it inside the body
    would have the guide teach and then ask in the same breath, with nothing
    waiting for the answer.
    """
    lines = [str(line).strip() for line in copy if str(line).strip()]
    if lines and lines[-1].endswith("?"):
        return lines[:-1], lines[-1]
    return lines, ""


@lru_cache(maxsize=1)
def load_topics() -> list[dict[str, Any]]:
    """The authored topics, or an empty list if the file is unreadable."""
    try:
        return list(json.loads(CONTENT.read_text())["topics"])
    except Exception:
        logger.error(
            "The eleven authored topics could not be read from %s, so the "
            "tutor keeps only the six concepts the module teaches.",
            CONTENT,
            exc_info=True,
        )
        return []


def concept_rows() -> list[dict[str, Any]]:
    """One row per topic, shaped for the `concepts` table."""
    rows: list[dict[str, Any]] = []
    for topic in load_topics():
        title = str(topic.get("title") or "").strip()
        if not title:
            continue
        key = re.sub(r"[^a-z ]+", "", title.lower()).strip()
        cid = _EXISTING.get(key) or _ID.get(key) or _slug(title)

        bodies: dict[str, str] = {}
        checks: list[dict[str, Any]] = []
        voices = topic.get("voices") or {}
        for voice, band in _VOICE_BAND.items():
            copy = (voices.get(voice) or {}).get("copy") or []
            teaching, question = _split_check(list(copy))
            if teaching:
                bodies[band] = " ".join(teaching)
            if question:
                checks.append(
                    {
                        "id": f"t{topic.get('n', 0)}_{band.replace('-', '_')}",
                        "band": band.replace("-", "_"),
                        "type": "short_answer",
                        "question": question,
                        "answer": "",
                        "accept": [],
                        "hints": [],
                    }
                )
        if not bodies:
            continue

        present = [b for b in _BAND_ORDER if b in bodies]
        rows.append(
            {
                "id": cid,
                "title": title,
                "bodies": bodies,
                "check_bank": checks,
                "band_min": present[0],
                "band_max": present[-1],
                # The author's note on why a band is written the way it is.
                "local_example": str((voices.get("kaleb") or {}).get("note") or "")[:400],
                "enriches_existing": cid in _EXISTING.values(),
            }
        )
    return rows
