"""Persisting an application slot by slot, with PII encrypted and separated."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any

from app.agents.register.schema import Slot, child_key, slot_for
from app.config import get_settings

logger = logging.getLogger(__name__)


class EncryptionUnavailable(RuntimeError):
    """No PII key is configured. Registration will not persist a sensitive slot."""


@lru_cache(maxsize=1)
def _fernet():
    key = get_settings().pii_encryption_key
    if not key:
        raise EncryptionUnavailable(
            "PII_ENCRYPTION_KEY is not set, so a national ID or a date of birth "
            "cannot be stored safely. Generate one with:\n"
            "    python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())"'
        )
    from cryptography.fernet import Fernet

    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> bytes:
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt(blob: bytes) -> str:
    return _fernet().decrypt(blob).decode("utf-8")


def _serialise(value: Any) -> str:
    """A slot value as the string that gets encrypted or stored."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _deserialise(slot: Slot, raw: str) -> Any:
    """The inverse, driven by the slot's own parser."""
    value, problem = slot.parse(raw)
    return raw if problem else value


@dataclass
class Draft:
    """One application in progress, as the graph holds it."""

    application_id: str
    resume_token: str
    values: dict[str, Any] = field(default_factory=dict)
    child_index: int = 0
    children_complete: int = 0
    status: str = "draft"
    pending_corrections: list[str] = field(default_factory=list)
    #: Optional slots the parent declined, as resolved keys (`child.0.photo`).
    skipped: list[str] = field(default_factory=list)

    def key_for(self, path: str) -> str:
        return child_key(path, self.child_index)

    def get(self, path: str) -> Any:
        return self.values.get(self.key_for(path))

    def set(self, path: str, value: Any) -> None:
        self.values[self.key_for(path)] = value

    @property
    def in_correction_mode(self) -> bool:
        return bool(self.pending_corrections)


def new_draft(session_id: str | None = None) -> Draft:
    import uuid

    return Draft(
        application_id=str(uuid.uuid4()),
        # 32 bytes of urlsafe randomness.
        resume_token=secrets.token_urlsafe(32),
    )


# ── persistence ──────────────────────────────────────────────────────────────


async def open_application(draft: Draft, *, session_id: str | None, owner: str | None) -> None:
    """Create the row before the first question is asked."""
    from sqlalchemy import text as sql

    from app.db import session

    async with session() as db:
        if db is None:
            return
        await db.execute(
            sql(
                """
                INSERT INTO applications (id, session_id, owner_user_id, resume_token)
                VALUES (CAST(:id AS uuid), :session, :owner, :token)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": draft.application_id,
                "session": session_id,
                "owner": owner,
                "token": draft.resume_token,
            },
        )
        await db.commit()


async def save_slot(draft: Draft, path: str, value: Any) -> None:
    """Write one answer, immediately, to the right table."""
    slot = slot_for(path)
    if slot is None:
        raise ValueError(f"{path!r} is not a slot")

    key = draft.key_for(path)
    draft.values[key] = value

    from sqlalchemy import text as sql

    from app.db import session

    async with session() as db:
        if db is None:
            # No database is a supported state for the tests and for a local run.
            return

        if slot.sensitive:
            blob = encrypt(_serialise(value))
            await db.execute(
                sql(
                    """
                    INSERT INTO application_pii (application_id, slot, value_encrypted)
                    VALUES (CAST(:id AS uuid), :slot, :blob)
                    ON CONFLICT (application_id, slot)
                    DO UPDATE SET value_encrypted = EXCLUDED.value_encrypted
                    """
                ),
                {"id": draft.application_id, "slot": key, "blob": blob},
            )
        else:
            # The casts are load-bearing, not decoration.
            await db.execute(
                sql(
                    """
                    UPDATE applications
                       SET answers = answers || jsonb_build_object(
                               CAST(:slot AS text), to_jsonb(CAST(:value AS text))
                           ),
                           updated_at = now()
                     WHERE id = CAST(:id AS uuid)
                    """
                ),
                {
                    "id": draft.application_id,
                    "slot": key,
                    "value": _serialise(value),
                },
            )
        await db.commit()

    logger.info(
        "slot saved application=%s slot=%s sensitive=%s",
        draft.application_id,
        key,
        slot.sensitive,
    )


async def load_draft(resume_token: str) -> Draft | None:
    """Reopen an application from its resume token."""
    from sqlalchemy import text as sql

    from app.db import session

    async with session() as db:
        if db is None:
            return None
        row = (
            await db.execute(
                sql(
                    """
                    SELECT id, answers, status, pending_corrections
                      FROM applications
                     WHERE resume_token = :token
                    """
                ),
                {"token": resume_token},
            )
        ).first()
        if row is None:
            return None

        pii_rows = (
            await db.execute(
                sql(
                    """
                    SELECT slot, value_encrypted
                      FROM application_pii
                     WHERE application_id = :id
                    """
                ),
                {"id": row[0]},
            )
        ).all()

    draft = Draft(
        application_id=str(row[0]),
        resume_token=resume_token,
        values=dict(row[1] or {}),
        status=row[2],
        pending_corrections=list(row[3] or []),
    )

    for slot_key, blob in pii_rows:
        base = slot_key.split(".", 2)
        path = f"{base[0]}.{base[-1]}" if base[0] == "child" else slot_key
        slot = slot_for(path)
        try:
            raw = decrypt(bytes(blob))
        except Exception:
            # A row that will not decrypt is a key rotation gone wrong.
            logger.error(
                "Could not decrypt %s for application %s; it will be re-asked.",
                slot_key,
                draft.application_id,
            )
            continue
        draft.values[slot_key] = _deserialise(slot, raw) if slot else raw

    # Which child we are on: the highest index that has any value.
    indices = [
        int(key.split(".")[1])
        for key in draft.values
        if key.startswith("child.") and key.split(".")[1].isdigit()
    ]
    draft.child_index = max(indices) if indices else 0
    return draft


async def record_documents(draft: Draft, rows: list[dict[str, Any]]) -> None:
    """Insert document rows once the client confirms the PUT succeeded."""
    if not rows:
        return
    from sqlalchemy import text as sql

    from app.db import session

    async with session() as db:
        if db is None:
            return
        for row in rows:
            await db.execute(
                sql(
                    """
                    INSERT INTO documents_uploaded (
                        id, application_id, slot, storage_key, mime, size_bytes,
                        uploaded_by, scan_status
                    ) VALUES (
                        :id, CAST(:application_id AS uuid), :slot, :storage_key,
                        :mime, :size_bytes, :uploaded_by, :scan_status
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                row,
            )
        await db.commit()


async def attest_and_submit(
    draft: Draft, *, consent_version: str, ip: str | None
) -> None:
    """Record the attestation and move the application into the queue."""
    from sqlalchemy import text as sql

    from app.db import session

    draft.status = "submitted"

    async with session() as db:
        if db is None:
            return
        await db.execute(
            sql(
                """
                UPDATE applications
                   SET status = 'submitted',
                       consent_version = :version,
                       attested_at = :at,
                       attested_ip = :ip,
                       submitted_at = now(),
                       pending_corrections = '{}',
                       updated_at = now()
                 WHERE id = CAST(:id AS uuid)
                """
            ),
            {
                "id": draft.application_id,
                "version": consent_version,
                "at": datetime.now(timezone.utc),
                "ip": ip,
            },
        )
        await db.execute(
            sql(
                """
                INSERT INTO review_events (application_id, actor, from_status,
                                           to_status, reason)
                VALUES (CAST(:id AS uuid), :actor, 'draft', 'submitted',
                        'Submitted by the guardian')
                """
            ),
            {"id": draft.application_id, "actor": "guardian"},
        )
        await db.commit()

    logger.info(
        "application %s submitted (consent %s)", draft.application_id, consent_version
    )
