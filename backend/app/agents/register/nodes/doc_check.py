"""A vision model looks at the document and says what it thinks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: Below this the note says "hard to read" and a retake may be offered ONCE.
RETAKE_THRESHOLD = 0.55

#: Below this the flag is raised for the reviewer regardless of retakes.
FLAG_THRESHOLD = 0.75

MAX_RETAKES = 1

_SYSTEM = """You are checking a photo of an official document for an application.

Answer four questions and nothing else:
  1. Is this the document type asked for?
  2. Can every line of text be read?
  3. Is the whole page in frame, with no corner cut off?
  4. Does the name on it roughly match the name given?

"Roughly" is doing real work in question 4. Spelling variants, a middle name
present on one and not the other, and a different transliteration are all
MATCHES. Only a plainly different person is a mismatch.

Reply with JSON only:
  {"expected_type": true/false, "legible": true/false, "whole_page": true/false,
   "name_matches": true/false, "confidence": 0.0-1.0, "notes": "<one sentence>"}
"""


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the model thought. Never what happens."""

    expected_type: bool = True
    legible: bool = True
    whole_page: bool = True
    name_matches: bool = True
    confidence: float = 1.0
    notes: str = ""
    #: True when the model could not be reached or its answer was unusable.
    unavailable: bool = False

    @property
    def should_flag(self) -> bool:
        """Whether a reviewer should be told to look closely."""
        if self.unavailable:
            return False
        return (
            self.confidence < FLAG_THRESHOLD
            or not self.expected_type
            or not self.legible
            or not self.whole_page
            or not self.name_matches
        )

    @property
    def retake_worth_asking(self) -> bool:
        """Whether a retake would plausibly help."""
        if self.unavailable:
            return False
        return (not self.legible or not self.whole_page) and self.confidence < RETAKE_THRESHOLD


def _parse(raw: str) -> Verdict:
    import json

    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return Verdict(unavailable=True, notes="no verdict")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return Verdict(unavailable=True, notes="unparseable verdict")
    if not isinstance(data, dict):
        return Verdict(unavailable=True, notes="unparseable verdict")

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    return Verdict(
        expected_type=bool(data.get("expected_type", True)),
        legible=bool(data.get("legible", True)),
        whole_page=bool(data.get("whole_page", True)),
        name_matches=bool(data.get("name_matches", True)),
        confidence=max(0.0, min(1.0, confidence)),
        notes=str(data.get("notes") or "")[:280],
    )


#: Retake copy.
_RETAKE: dict[str, str] = {
    "en": "That photo's a bit hard to read at the bottom — mind taking it again?",
    "es": "Esa foto cuesta un poco de leer abajo — ¿la tomas otra vez?",
    "fr": "Cette photo est un peu difficile à lire en bas — tu peux la reprendre ?",
}


def retake_message(verdict: Verdict, locale: str) -> str:
    """What to say when asking for one more photo. Once, ever."""
    base = _RETAKE.get(locale) or _RETAKE["en"]
    if not verdict.whole_page and verdict.legible:
        return {
            "en": "I think a corner is cut off — could you get the whole page in?",
            "es": "Creo que falta una esquina — ¿puedes incluir toda la página?",
            "fr": "Il manque un coin, je crois — tu peux prendre toute la page ?",
        }.get(locale, base)
    return base


def make_doc_check(invoke=None):
    """Build the node."""

    async def doc_check(state: Any) -> dict[str, Any]:
        registration = state.get("registration") or {}
        document = registration.get("__last_document")
        if not isinstance(document, dict) or not document.get("document_id"):
            return {}

        slot_path = str(document.get("slot") or registration.get("awaiting") or "")
        retakes = int(document.get("retakes_requested") or 0)
        locale = str(state.get("locale") or "en")

        if invoke is None:
            return {}

        try:
            from app.storage.presign import presign_download

            url = presign_download(str(document.get("storage_key") or ""), ttl_seconds=120)
            raw = await invoke(_SYSTEM, url, _context(state, slot_path))
            verdict = _parse(raw)
        except Exception:
            # No opinion.
            logger.warning("doc_check unavailable; proceeding.", exc_info=True)
            verdict = Verdict(unavailable=True, notes="check unavailable")

        # Logged alongside the document so agreement with the eventual human decision can be MEASURED.
        logger.info(
            "doc_check document=%s slot=%s confidence=%.2f flag=%s notes=%r",
            document.get("document_id"),
            slot_path,
            verdict.confidence,
            verdict.should_flag,
            verdict.notes[:80],
        )

        updated = {
            **document,
            "check_confidence": verdict.confidence,
            "check_notes": verdict.notes,
            "flagged": verdict.should_flag,
        }

        # Written to the document row whatever the outcome.
        try:
            await record_verdict(str(document["document_id"]), verdict)
        except Exception:
            logger.warning(
                "Could not record the doc_check verdict for %s.",
                document.get("document_id"),
                exc_info=True,
            )

        if verdict.retake_worth_asking and retakes < MAX_RETAKES:
            from langchain_core.messages import AIMessage

            updated["retakes_requested"] = retakes + 1
            # The slot is CLEARED so the loop asks for it again.
            values = dict(registration.get("values") or {})
            if slot_path:
                index = registration.get("child_index", 0)
                key = (
                    f"child.{index}.{slot_path[len('child.'):]}"
                    if slot_path.startswith("child.")
                    else slot_path
                )
                values.pop(key, None)
            return {
                "messages": [AIMessage(content=retake_message(verdict, locale))],
                "registration": {
                    **registration,
                    "values": values,
                    "__last_document": updated,
                },
            }

        # Past the cap, or nothing a retake would fix. ACCEPTED and flagged.
        if verdict.should_flag:
            logger.info(
                "Accepting document %s with a flag for the reviewer.",
                document.get("document_id"),
            )
        return {
            "registration": {
                **registration,
                # Cleared so the next slot's `_after_doc_check` does not read a stale retake flag and end the turn again.
                "__last_document": None,
                "__last_verdict": {
                    "document_id": document.get("document_id"),
                    "confidence": verdict.confidence,
                    "flagged": verdict.should_flag,
                },
            }
        }

    return doc_check


def _context(state: Any, slot_path: str) -> str:
    """What the model is told about what it is looking at."""
    registration = state.get("registration") or {}
    values = registration.get("values") or {}
    expected_name = (
        values.get("guardian.full_name")
        if slot_path.startswith("guardian.")
        else values.get(f"child.{registration.get('child_index', 0)}.full_name")
    )
    document_type = {
        "guardian.id_document": "a government photo ID",
        "guardian.proof_of_address": "a bill or letter showing an address",
        "child.birth_certificate": "a birth certificate",
        "child.photo": "a photo of a child's face",
    }.get(slot_path, "an official document")

    return (
        f"Expected document: {document_type}.\n"
        f"Expected name: {expected_name or 'unknown'}."
    )


def vision_invoke():
    """The real vision call, or None if no vision model is configured."""
    from app.config import get_settings

    settings = get_settings()
    model_name = settings.doc_check_model
    if not model_name:
        logger.info(
            "DOC_CHECK_MODEL is unset, so uploaded documents go straight to the "
            "human queue with no automated opinion."
        )
        return None

    provider = model_name.split(":", 1)[0].lower()
    has_key = {
        "anthropic": bool(settings.anthropic_api_key),
        "openai": bool(settings.openai_api_key),
    }.get(provider)
    if has_key is False:
        logger.warning(
            "DOC_CHECK_MODEL is %r but there is no %s key; documents will go to "
            "the human queue with no automated opinion.",
            model_name,
            provider,
        )
        return None

    async def invoke(system: str, image_url: str, context: str) -> str:
        from langchain.chat_models import init_chat_model
        from langchain_core.messages import HumanMessage, SystemMessage

        model = init_chat_model(model_name)
        response = await model.ainvoke(
            [
                SystemMessage(content=system),
                HumanMessage(
                    content=[
                        {"type": "text", "text": context},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ]
                ),
            ]
        )
        content = response.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return ""

    logger.info("Document checks will use %s (advisory only).", model_name)
    return invoke


async def record_verdict(document_id: str, verdict: Verdict) -> None:
    """Write the advisory verdict onto the document row for the admin queue."""
    from sqlalchemy import text as sql

    from app.db import session

    async with session() as db:
        if db is None:
            return
        await db.execute(
            sql(
                """
                UPDATE documents_uploaded
                   SET check_confidence = :confidence,
                       check_notes = :notes
                 WHERE id = :id
                """
            ),
            {
                "id": document_id,
                "confidence": verdict.confidence,
                "notes": verdict.notes,
            },
        )
        await db.commit()
