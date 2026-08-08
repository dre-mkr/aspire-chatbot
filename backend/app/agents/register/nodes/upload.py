"""Collecting a document by pausing the graph.

    doc = interrupt({
        "type": "upload_request",
        "slot": "child.birth_certificate",
        "label": "Rachel's birth certificate",
        "accepts": [...],
        "max_mb": 10,
        "help": "A clear photo of the whole page is fine.",
    })

`interrupt()` suspends the graph mid-node. The checkpoint holds everything, the
frontend renders `UploadCard`, and `Command(resume=...)` continues from the
same line with the document id.

## Why an interrupt rather than a state flag and a second turn

A slot loop that emitted "please upload" and ended the turn would have to
re-derive, on the next turn, which slot that upload belongs to -- from state
that the parent may have changed by typing something else. `interrupt` keeps the
question and the answer in the same stack frame, so the pairing cannot come
apart.

It also means an upload that never arrives leaves the graph paused rather than
advanced, which is the correct state: the slot is not filled.

## The graph receives an id. Never bytes.

The client PUTs to object storage directly (`storage/presign.py`). What crosses
this boundary is `{"document_id": ..., "mime": ..., "size_bytes": ...}` -- a few
dozen bytes of JSON. No file content enters graph state, a log line, a
checkpoint, or a model context.

`_assert_no_bytes` is not decoration: a future client that "helpfully" included
a base64 preview would otherwise write a birth certificate into a Postgres
checkpoint that gets replayed into a prompt.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.register.schema import Slot
from app.schemas.directives import UploadDirective, directive_payload

logger = logging.getLogger(__name__)

ACCEPTS: list[str] = ["image/jpeg", "image/png", "image/heic", "application/pdf"]

MAX_MB = 10

#: Keys a resume payload may carry. Anything else is dropped with a warning --
#: see `_assert_no_bytes`.
_ALLOWED_RESUME_KEYS = frozenset(
    {"document_id", "mime", "size_bytes", "checksum", "storage_key", "skipped"}
)

HELP: dict[str, dict[str, str]] = {
    "guardian.id_document": {
        "en": "A clear photo of the whole card is fine.",
        "es": "Una foto clara de toda la tarjeta está bien.",
        "fr": "Une photo claire de toute la carte suffit.",
    },
    "guardian.proof_of_address": {
        "en": "A bill or a letter with your address on it.",
        "es": "Una factura o carta con tu dirección.",
        "fr": "Une facture ou une lettre avec ton adresse.",
    },
    "child.birth_certificate": {
        "en": "A clear photo of the whole page is fine.",
        "es": "Una foto clara de toda la página está bien.",
        "fr": "Une photo claire de toute la page suffit.",
    },
    "child.photo": {
        "en": "Just their face, looking at the camera.",
        "es": "Solo su cara, mirando a la cámara.",
        "fr": "Juste son visage, face à l'appareil.",
    },
}


def upload_directive(slot: Slot, locale: str, *, label: str | None = None) -> Any:
    """The card the client renders while the graph is paused."""
    return UploadDirective(
        slot=slot.path,
        label=label or slot.label,
        accepts=ACCEPTS,
        max_mb=MAX_MB,
        help=(HELP.get(slot.path, {}).get(locale) or HELP.get(slot.path, {}).get("en", "")),
        # Carried from the slot table, so the card offers skip on exactly the
        # documents `collect` will accept a skip for. Deriving it here rather
        # than listing paths in the client keeps one definition of optional.
        optional=slot.optional,
    )


def interrupt_payload(slot: Slot, locale: str, *, label: str | None = None) -> dict[str, Any]:
    """What `interrupt()` is handed. Mirrors the directive, plus a type tag."""
    directive = upload_directive(slot, locale, label=label)
    return {"type": "upload_request", **directive_payload(directive)}


def _assert_no_bytes(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip anything that is not an identifier, loudly.

    The failure this prevents: a client that includes a base64 thumbnail "for
    convenience". That string would be written into the checkpoint, which is
    Postgres, and replayed into the model's context on the next turn -- putting
    a child's birth certificate in a prompt by accident.
    """
    unexpected = set(payload) - _ALLOWED_RESUME_KEYS
    if unexpected:
        logger.warning(
            "Upload resume payload carried unexpected key(s) %s; dropped. "
            "Only identifiers cross this boundary.",
            ", ".join(sorted(unexpected)),
        )
    return {key: value for key, value in payload.items() if key in _ALLOWED_RESUME_KEYS}


def make_collect_document(slot: Slot, locale: str, *, label: str | None = None):
    """A node that pauses for one document and resumes with its id.

    Written as a factory returning a node rather than as a node reading the slot
    from state, because `interrupt` resumes INTO THIS FUNCTION -- the slot has to
    be closed over, or the resumed call would have to re-derive which document
    it is holding.
    """

    def collect_document(state: Any) -> dict[str, Any]:
        from langgraph.types import interrupt

        raw = interrupt(interrupt_payload(slot, locale, label=label))
        payload = _assert_no_bytes(raw if isinstance(raw, dict) else {})

        if payload.get("skipped") and slot.optional:
            logger.info("document slot %s skipped", slot.path)
            return {"registration": {"__last_document": None}}

        document_id = payload.get("document_id")
        if not document_id:
            # Resumed with nothing usable. The slot stays unfilled and the loop
            # asks again, which is correct: an upload that did not happen must
            # not advance the form.
            logger.info("document slot %s resumed with no id", slot.path)
            return {}

        logger.info(
            "document %s collected for %s (%s, %d bytes)",
            document_id,
            slot.path,
            payload.get("mime", "?"),
            int(payload.get("size_bytes") or 0),
        )
        return {
            "registration": {
                "__last_document": {
                    "document_id": str(document_id),
                    "mime": str(payload.get("mime") or ""),
                    "size_bytes": int(payload.get("size_bytes") or 0),
                    # Never `clean`. A document nobody scanned is not clean, and
                    # this is the value the admin queue reads.
                    "scan_status": "pending",
                }
            }
        }

    return collect_document


def document_ref(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """The `DocumentRef` shape a slot stores, from a resume payload."""
    if not payload or not payload.get("document_id"):
        return None
    return {
        "document_id": payload["document_id"],
        "mime": payload.get("mime", ""),
        "size_bytes": int(payload.get("size_bytes") or 0),
        "scan_status": "pending",
        "check_confidence": 0.0,
        "check_notes": "",
    }
