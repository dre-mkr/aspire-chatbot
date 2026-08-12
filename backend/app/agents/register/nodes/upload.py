"""Collecting a document by pausing the graph."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.register.schema import Slot
from app.schemas.directives import UploadDirective, directive_payload

logger = logging.getLogger(__name__)

ACCEPTS: list[str] = ["image/jpeg", "image/png", "image/heic", "application/pdf"]

MAX_MB = 10

#: Keys a resume payload may carry.
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


def upload_directive(
    slot: Slot,
    locale: str,
    *,
    label: str | None = None,
    application_id: str = "",
) -> Any:
    """The card the client renders while the graph is paused."""
    return UploadDirective(
        slot=slot.path,
        label=label or slot.label,
        accepts=ACCEPTS,
        max_mb=MAX_MB,
        help=(HELP.get(slot.path, {}).get(locale) or HELP.get(slot.path, {}).get("en", "")),
        # From the slot table, so the card offers skip on exactly the documents `collect` allows.
        optional=slot.optional,
        application_id=application_id,
    )


def interrupt_payload(
    slot: Slot,
    locale: str,
    *,
    label: str | None = None,
    application_id: str = "",
) -> dict[str, Any]:
    """What `interrupt()` is handed. Mirrors the directive, plus a type tag."""
    directive = upload_directive(
        slot, locale, label=label, application_id=application_id
    )
    return {"type": "upload_request", **directive_payload(directive)}


def _assert_no_bytes(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip anything that is not an identifier, loudly."""
    unexpected = set(payload) - _ALLOWED_RESUME_KEYS
    if unexpected:
        logger.warning(
            "Upload resume payload carried unexpected key(s) %s; dropped. "
            "Only identifiers cross this boundary.",
            ", ".join(sorted(unexpected)),
        )
    return {key: value for key, value in payload.items() if key in _ALLOWED_RESUME_KEYS}


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
