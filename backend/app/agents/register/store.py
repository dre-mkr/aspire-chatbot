"""Persisting an application slot by slot, with PII encrypted and separated.

## Every slot is written the moment it is answered

Not at the end of a section, not on submit. A parent doing this on a phone
between other things will not finish in one sitting -- they will be
interrupted, their battery will die, or they will simply close it and come back
on Thursday. An application that only persists at the end is an application most
parents never complete, and nothing about that failure is visible: it looks like
people losing interest.

`resume_token` is what brings them back to the exact next question.

## Sensitive values go to `application_pii`, encrypted, and nowhere else

`Slot.sensitive` decides it. The value is Fernet-encrypted with
`PII_ENCRYPTION_KEY` and written to a table the queue query never joins, so
reading a child's date of birth is a separate act that can be logged.

## Without a key, it REFUSES

`save_slot` raises rather than falling back to plaintext. A registration flow
that quietly degrades to storing national ID numbers in a JSONB column when an
environment variable is missing is worse than one that stops -- the second
failure is loud on the first deploy, and the first is discovered in a breach
report.
"""

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


def encryption_available() -> bool:
    try:
        _fernet()
        return True
    except Exception:
        return False


def _serialise(value: Any) -> str:
    """A slot value as the string that gets encrypted or stored.

    Dates go ISO so they round-trip; everything else is `str`. `repr` is
    deliberately not used -- a value that round-trips through `repr` and back
    through `str` is a value that gains quotes each time it is edited.
    """
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _deserialise(slot: Slot, raw: str) -> Any:
    """The inverse, driven by the slot's own parser.

    Using the parser rather than a type tag means there is one definition of
    what a slot's value is, and a change to the parser cannot leave old rows
    reading back as something else.
    """
    value, problem = slot.parse(raw)
    return raw if problem else value


@dataclass
class Draft:
    """One application in progress, as the graph holds it.

    `values` is keyed by slot path, with child slots indexed
    (`child.0.full_name`). Documents are held as their `DocumentRef` dict.
    """

    application_id: str
    resume_token: str
    values: dict[str, Any] = field(default_factory=dict)
    child_index: int = 0
    children_complete: int = 0
    status: str = "draft"
    pending_corrections: list[str] = field(default_factory=list)
    #: Optional slots the parent declined, as resolved keys (`child.0.photo`).
    #:
    #: A list beside the values rather than a sentinel inside them. `next_missing`
    #: reads "unfilled" as `None` or `""`, so recording a skip as a value would
    #: either be indistinguishable from unanswered -- asking forever -- or would
    #: need a magic string, which `graph.pick_slot` already explains reached
    #: `submit` as a real answer the last time it was tried.
    #:
    #: Keys, not paths, because `child.photo` is skippable per child: declining a
    #: photo for the first child must not decline it for the second.
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
        # 32 bytes of urlsafe randomness. This is the only credential that
        # reopens a draft from another device, so it is sized like one.
        resume_token=secrets.token_urlsafe(32),
    )


# ── persistence ──────────────────────────────────────────────────────────────


async def open_application(draft: Draft, *, session_id: str | None, owner: str | None) -> None:
    """Create the row before the first question is asked.

    Ahead of the conversation rather than after it, for the same reason
    `_open_conversation` is: an application a parent started must exist even if
    the first answer never arrives, or the resume link they were given points at
    nothing.
    """
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
    """Write one answer, immediately, to the right table.

    Sensitive to `application_pii`, encrypted. Everything else to
    `applications.answers`. There is no third branch and no fallback -- see the
    module docstring for why a missing key raises here.
    """
    slot = slot_for(path)
    if slot is None:
        raise ValueError(f"{path!r} is not a slot")

    key = draft.key_for(path)
    draft.values[key] = value

    from sqlalchemy import text as sql

    from app.db import session

    async with session() as db:
        if db is None:
            # No database is a supported state for the tests and for a local
            # run. The draft still holds the value in memory, so the
            # conversation works and nothing resumes -- which is the honest
            # behaviour rather than a silent half-persistence.
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
            #
            # `to_jsonb` and `jsonb_build_object` are polymorphic, and asyncpg
            # sends a bind parameter with no type attached. Postgres cannot
            # resolve `to_jsonb(unknown)` and raises
            #
            #     DatatypeMismatchError: could not determine polymorphic type
            #     because input has type unknown
            #
            # so EVERY non-sensitive slot failed to save. The first three slots
            # are sensitive and take the branch above, which is why registration
            # got as far as the guardian's name, ID and date of birth before
            # dying on `guardian.relationship` -- far enough in to look like it
            # worked and to have collected real PII first.
            #
            # `text` rather than a typed cast per slot, because `_serialise`
            # already returns a string for every value including dates and
            # booleans, and the load path reads `answers` back verbatim without
            # `_deserialise`. Storing a real JSON boolean here would round-trip
            # `child.existing_account` as Python True where the rest of this
            # module expects the string "true".
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
    """Reopen an application from its resume token.

    Loads the non-sensitive answers and the PII together, because the graph
    needs to know which slots are FILLED in order to find the next one -- and a
    slot that is filled but invisible would be asked for again.
    """
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
            # A row that will not decrypt is a key rotation gone wrong. Logged
            # and skipped rather than raised: the parent should be asked for
            # that one field again, not shown an error.
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
    """Record the attestation and move the application into the queue.

    The consent VERSION is written in the same statement as the timestamp, so
    there is no window in which an application is attested and nobody knows to
    what. The schema's check constraint enforces the same thing from below.
    """
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
