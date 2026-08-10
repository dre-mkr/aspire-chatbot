"""Review, edit one field, attest, submit."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.agents.register.schema import display_value, slot_for

logger = logging.getLogger(__name__)

#: Bumped when the wording below changes. Never reused.
CONSENT_VERSION = "2026-08-v1"

CONSENT_TEXT: dict[str, str] = {
    "en": (
        "I confirm the details above are correct and I am the parent or legal "
        "guardian of the child named. I agree that ASPIRE may verify them."
    ),
    "es": (
        "Confirmo que los datos anteriores son correctos y que soy el padre, la "
        "madre o el tutor legal del menor indicado. Acepto que ASPIRE los "
        "verifique."
    ),
    "fr": (
        "Je confirme que les informations ci-dessus sont exactes et que je suis "
        "le parent ou le tuteur légal de l'enfant nommé. J'accepte qu'ASPIRE "
        "les vérifie."
    ),
}


@dataclass(frozen=True, slots=True)
class Attestation:
    """What is recorded when a guardian confirms."""

    consent_version: str
    at: datetime
    ip: str | None
    actor: str | None


def attestation_for(
    *, ip: str | None, actor: str | None, version: str = CONSENT_VERSION
) -> Attestation:
    return Attestation(
        consent_version=version,
        at=datetime.now(timezone.utc),
        ip=ip,
        actor=actor,
    )


def jump_to_slot(registration: dict[str, Any], slot_path: str) -> dict[str, Any]:
    """Reopen ONE slot and remember to come straight back to review."""
    slot = slot_for(_base_path(slot_path))
    if slot is None:
        logger.info("Ignoring an edit request for unknown slot %r.", slot_path)
        return registration

    values = dict(registration.get("values") or {})
    values.pop(slot_path, None)
    values["__awaiting"] = _base_path(slot_path)

    logger.info("editing slot %s; will return to review", slot_path)
    return {
        **registration,
        "values": values,
        "phase": "editing",
        # The flag the router reads after the answer lands.
        "return_to_review": True,
        "editing_key": slot_path,
    }


def _base_path(key: str) -> str:
    """`child.0.full_name` -> `child.full_name`. Guardian keys pass through."""
    parts = key.split(".")
    if len(parts) == 3 and parts[0] == "child" and parts[1].isdigit():
        return f"child.{parts[2]}"
    return key


def after_edit(registration: dict[str, Any]) -> str:
    """Where to go once an edited slot has been answered."""
    return "review" if registration.get("return_to_review") else "ask"


def summarise_for_reviewer(registration: dict[str, Any]) -> dict[str, Any]:
    """What goes into the admin queue row."""
    values = registration.get("values") or {}
    fields: list[tuple[str, str, str]] = []
    for key, value in values.items():
        if key.startswith("__"):
            continue
        slot = slot_for(_base_path(key))
        if slot is None:
            continue
        fields.append((key, slot.label, display_value(slot, value)))
    return {"fields": fields}


def make_confirm(notifier=None):
    """Tell the parent it is in, in the chat and by email or SMS."""

    async def confirm(state: Any) -> dict[str, Any]:
        from langchain_core.messages import AIMessage

        registration = state.get("registration") or {}
        locale = str(state.get("locale") or "en")
        application_id = str(registration.get("application_id") or "")
        reference = application_id[:8].upper()

        if notifier is not None:
            contact = (registration.get("values") or {}).get("guardian.email") or (
                registration.get("values") or {}
            ).get("guardian.phone")
            try:
                await notifier(application_id, contact)
            except Exception:
                logger.warning(
                    "Could not notify the guardian for application %s; it is still "
                    "submitted.",
                    application_id,
                    exc_info=True,
                )

        message = {
            "en": (
                f"That is submitted. Your reference is {reference}. ASPIRE will "
                "come back to you within five working days, and I have sent a "
                "copy of this to you."
            ),
            "es": (
                f"Enviado. Tu referencia es {reference}. ASPIRE te responderá en "
                "cinco días hábiles y te he enviado una copia."
            ),
            "fr": (
                f"C'est envoyé. Ta référence est {reference}. ASPIRE te répondra "
                "sous cinq jours ouvrables et je t'en ai envoyé une copie."
            ),
        }.get(locale)

        return {
            "messages": [AIMessage(content=message or "Submitted.")],
            "quick_replies": _chips(locale),
            "registration": {**registration, "phase": "done"},
        }

    return confirm


def _chips(locale: str) -> list[str]:
    return {
        "en": ["Add another child", "Something else"],
        "es": ["Añadir otro niño", "Otra cosa"],
        "fr": ["Ajouter un enfant", "Autre chose"],
    }.get(locale, ["Add another child", "Something else"])
