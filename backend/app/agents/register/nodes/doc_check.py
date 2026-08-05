"""A vision model looks at the document and says what it thinks. Advisory only.

Four questions:

    is this the expected document type?
    is it legible?
    is the whole page visible?
    does the name roughly match the one entered?

## It never rejects anything

Not "rarely". Never. There is no code path here that fails an application, and
`block_submission` does not exist. The verdict is a confidence number and a note
for the admin queue, and a human decides.

The reason is not modesty about the model. It is that the cost of a false
negative falls entirely on a family: a birth certificate that photographs badly
because the paper is old, a name that transliterates differently, a page whose
corner is cut off by a cracked phone screen. Every one of those is a real
document and a real child, and an automated rejection turns them into a family
who tried and was told no by something that cannot be argued with.

## One retake request per document, and the cap is in the schema

    CHECK (retakes_requested <= 1)

Asking twice is how a parent learns the app cannot be satisfied. After one
retake the document is ACCEPTED and flagged, and a reviewer sees both the flag
and the note.

## The verdict is logged next to the human decision

That is the only way anybody earns the right to trust this later. `verdicts` and
the eventual `review_events` row are joined by application; agreement rate is a
query, not an impression. Until that number exists, this changes nothing about
what gets approved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: Below this the note says "hard to read" and a retake may be offered ONCE.
#: Above it the document passes silently -- a parent who took a good photo
#: should not be told anything at all.
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
    #: Treated as "no opinion", which means the document proceeds.
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
        """Whether a retake would plausibly help.

        Legibility and framing are fixable by taking another photo. A wrong
        document type or a mismatched name are NOT -- asking a parent to
        re-photograph a document that is simply the wrong one wastes their time
        and tells them nothing.
        """
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


#: Retake copy. Names the specific problem and stays cheerful -- a parent who
#: reads this as criticism of their photography stops taking photos.
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
    """Build the node. `invoke` is `async (system, image_url, context) -> str`.

    Injected, and `None` is a supported configuration rather than a test-only
    one: a deployment without a vision model runs registration unchanged, with
    every document passing silently to the human queue. That is exactly the
    behaviour before this node existed, which is what makes turning it on safe.
    """

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
            # No opinion. The document proceeds exactly as it would have without
            # this node -- a vision outage must not stop a family applying.
            logger.warning("doc_check unavailable; proceeding.", exc_info=True)
            verdict = Verdict(unavailable=True, notes="check unavailable")

        # Logged alongside the document so agreement with the eventual human
        # decision can be MEASURED. Nothing here acts on the verdict.
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

        # Written to the document row whatever the outcome. The whole point of
        # an advisory check is that its verdict can be compared against the
        # human decision later, and a verdict that was never stored cannot be.
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
            # The slot is CLEARED so the loop asks for it again. Without this
            # the retake request would be a sentence with nothing behind it --
            # the slot is already filled, so the walk would move on and the
            # parent would be asked to retake a document nobody was waiting for.
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
                # Cleared so the next slot's `_after_doc_check` does not read a
                # stale retake flag and end the turn again.
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
    """What the model is told about what it is looking at.

    The expected NAME is included because question 4 needs it. Nothing else
    from the application is -- the model does not need the address, the ID
    number or the date of birth to say whether a page is in focus.
    """
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
    """The real vision call, or None if no vision model is configured.

    `async (system, image_url, context) -> str`. None is a first-class return
    and the caller treats it as "no opinion" -- every document then passes
    silently to the human queue, which is exactly the behaviour before this node
    existed. That is what makes enabling it a safe change rather than a leap.

    The image is passed as a SHORT-LIVED SIGNED URL rather than as base64. Two
    reasons and the second is the one that matters: a 10MB base64 blob in a
    request body is a 13MB request, and -- far worse -- it would put the bytes
    of a child's birth certificate into a model prompt, a request log and
    whatever the provider retains. A URL that expires in two minutes puts a
    pointer there instead.
    """
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
