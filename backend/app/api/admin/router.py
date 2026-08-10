"""The admin API: the queue, one application, the status machine, the widget queue."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.admin.auth import (
    Staff,
    audit,
    audit_document,
    client_ip,
    current_staff,
    requires,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

Status = Literal[
    "submitted", "under_review", "info_requested", "approved", "rejected"
]

#: The only moves the machine allows.
TRANSITIONS: dict[str, frozenset[str]] = {
    "submitted": frozenset({"under_review"}),
    "under_review": frozenset({"info_requested", "approved", "rejected"}),
    # Back to review only.
    "info_requested": frozenset({"under_review"}),
    # Terminal.
    "approved": frozenset(),
    "rejected": frozenset(),
}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


# ── the queue ────────────────────────────────────────────────────────────────


class QueueRow(BaseModel):
    id: str
    status: str
    parish: str | None = None
    children: int = 0
    created_at: str
    #: How many documents `doc_check` flagged.
    flags: int = 0


@router.get("/applications")
async def queue(
    status: str | None = None,
    parish: str | None = None,
    since: str | None = None,
    flagged: bool = False,
    limit: int = 50,
    staff: Staff = Depends(current_staff),
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """The review queue."""
    from sqlalchemy import text as sql

    from app.db import session

    clauses = ["status <> 'draft'"]
    params: dict[str, Any] = {"limit": max(1, min(limit, 200))}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if parish:
        clauses.append("answers->>'guardian.parish' = :parish")
        params["parish"] = parish
    if since:
        clauses.append("created_at >= CAST(:since AS timestamptz)")
        params["since"] = since

    async with session() as db:
        if db is None:
            raise HTTPException(status_code=503, detail="No database is configured.")
        rows = (
            await db.execute(
                sql(
                    f"""
                    SELECT a.id,
                           a.status,
                           a.answers->>'guardian.parish' AS parish,
                           a.created_at,
                           (SELECT count(*) FROM application_children c
                             WHERE c.application_id = a.id) AS children,
                           (SELECT count(*) FROM documents_uploaded d
                             WHERE d.application_id = a.id
                               AND d.check_confidence IS NOT NULL
                               AND d.check_confidence < 0.75) AS flags
                      FROM applications a
                     WHERE {" AND ".join(clauses)}
                     ORDER BY a.created_at ASC
                     LIMIT :limit
                    """
                ),
                params,
            )
        ).all()

    result = [
        QueueRow(
            id=str(row[0]),
            status=row[1],
            parish=row[2],
            created_at=row[3].isoformat(),
            children=row[4],
            flags=row[5],
        ).model_dump()
        for row in rows
        if not flagged or row[5] > 0
    ]

    await audit(
        staff,
        action="queue.view",
        subject_type="queue",
        subject_id=status or "all",
        detail={"rows": len(result)},
        ip=client_ip(request) if request else None,
    )
    return {"rows": result}


# ── one application ──────────────────────────────────────────────────────────


@router.get("/applications/{application_id}")
async def detail(
    application_id: str,
    request: Request,
    staff: Staff = Depends(current_staff),
) -> dict[str, Any]:
    """Fields on the left, documents on the right."""
    from sqlalchemy import text as sql

    from app.agents.register.store import decrypt
    from app.db import session

    async with session() as db:
        if db is None:
            raise HTTPException(status_code=503, detail="No database is configured.")

        row = (
            await db.execute(
                sql(
                    """
                    SELECT id, status, answers, pending_corrections,
                           consent_version, attested_at, created_at, submitted_at
                      FROM applications
                     WHERE id = CAST(:id AS uuid)
                    """
                ),
                {"id": application_id},
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="No such application.")

        pii_rows = (
            await db.execute(
                sql(
                    "SELECT slot, value_encrypted FROM application_pii "
                    "WHERE application_id = CAST(:id AS uuid)"
                ),
                {"id": application_id},
            )
        ).all()
        documents = (
            await db.execute(
                sql(
                    """
                    SELECT id, slot, mime, size_bytes, scan_status,
                           check_confidence, check_notes, uploaded_at
                      FROM documents_uploaded
                     WHERE application_id = CAST(:id AS uuid)
                     ORDER BY uploaded_at
                    """
                ),
                {"id": application_id},
            )
        ).all()
        events = (
            await db.execute(
                sql(
                    """
                    SELECT actor, from_status, to_status, reason, slots_flagged,
                           created_at
                      FROM review_events
                     WHERE application_id = CAST(:id AS uuid)
                     ORDER BY created_at
                    """
                ),
                {"id": application_id},
            )
        ).all()

    await audit(
        staff,
        action="application.view",
        subject_type="application",
        subject_id=application_id,
        ip=client_ip(request),
    )

    fields = dict(row[2] or {})
    for slot, blob in pii_rows:
        try:
            fields[slot] = decrypt(bytes(blob))
        except Exception:
            fields[slot] = "[could not decrypt]"

    return {
        "id": str(row[0]),
        "status": row[1],
        "fields": fields,
        "pending_corrections": list(row[3] or []),
        "consent_version": row[4],
        "attested_at": row[5].isoformat() if row[5] else None,
        "created_at": row[6].isoformat(),
        "submitted_at": row[7].isoformat() if row[7] else None,
        "documents": [
            {
                "id": document[0],
                "slot": document[1],
                "mime": document[2],
                "size_bytes": document[3],
                "scan_status": document[4],
                "check_confidence": document[5],
                "check_notes": document[6],
                "uploaded_at": document[7].isoformat(),
            }
            for document in documents
        ],
        "history": [
            {
                "actor": event[0],
                "from": event[1],
                "to": event[2],
                "reason": event[3],
                "slots": list(event[4] or []),
                "at": event[5].isoformat(),
            }
            for event in events
        ],
    }


@router.get("/documents/{document_id}/url")
async def document_url(
    document_id: str,
    request: Request,
    staff: Staff = Depends(current_staff),
) -> dict[str, Any]:
    """A short-lived signed URL, and an audit row for having asked."""
    from sqlalchemy import text as sql

    from app.db import session
    from app.storage.presign import presign_download

    async with session() as db:
        if db is None:
            raise HTTPException(status_code=503, detail="No database is configured.")
        row = (
            await db.execute(
                sql(
                    "SELECT storage_key, application_id FROM documents_uploaded "
                    "WHERE id = :id"
                ),
                {"id": document_id},
            )
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No such document.")

    await audit_document(
        staff,
        document_id=document_id,
        application_id=str(row[1]),
        ip=client_ip(request),
    )
    return {"url": presign_download(row[0]), "expires_in": 900}


# ── the status machine ───────────────────────────────────────────────────────


class Transition(BaseModel):
    to: Status
    #: Required, and non-empty. See the module docstring.
    reason: str = Field(min_length=3, max_length=2000)
    #: For `info_requested` only: the specific slot paths to reopen.
    slots: list[str] = Field(default_factory=list)


@router.post("/applications/{application_id}/transition")
async def transition(
    application_id: str,
    body: Transition,
    request: Request,
    staff: Staff = Depends(requires("reviewer")),
) -> dict[str, Any]:
    """Move an application, with a reason, and reopen slots if asked."""
    from sqlalchemy import text as sql

    from app.agents.register.schema import slot_for
    from app.db import session

    if body.to == "info_requested" and not body.slots:
        raise HTTPException(
            status_code=400,
            detail="Say which fields need correcting. The parent should not have "
            "to guess, and they will not be asked to refill the form.",
        )

    unknown = [
        path
        for path in body.slots
        if slot_for(_base_path(path)) is None
    ]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown slot(s): {unknown}")

    async with session() as db:
        if db is None:
            raise HTTPException(status_code=503, detail="No database is configured.")

        current = (
            await db.execute(
                sql("SELECT status FROM applications WHERE id = CAST(:id AS uuid)"),
                {"id": application_id},
            )
        ).scalar_one_or_none()
        if current is None:
            raise HTTPException(status_code=404, detail="No such application.")

        if not can_transition(current, body.to):
            raise HTTPException(
                status_code=409,
                detail=f"{current} cannot move to {body.to}.",
            )

        await db.execute(
            sql(
                """
                UPDATE applications
                   SET status = :to,
                       pending_corrections = CAST(:slots AS text[]),
                       updated_at = now()
                 WHERE id = CAST(:id AS uuid)
                """
            ),
            {
                "id": application_id,
                "to": body.to,
                # Cleared on every transition that is not info_requested, so a corrected application does not carry its old fla…
                "slots": body.slots if body.to == "info_requested" else [],
            },
        )
        await db.execute(
            sql(
                """
                INSERT INTO review_events (application_id, actor, from_status,
                                           to_status, reason, slots_flagged)
                VALUES (CAST(:id AS uuid), :actor, :from_status, :to_status,
                        :reason, CAST(:slots AS text[]))
                """
            ),
            {
                "id": application_id,
                "actor": staff.staff_id,
                "from_status": current,
                "to_status": body.to,
                "reason": body.reason,
                "slots": body.slots,
            },
        )
        await db.commit()

    await audit(
        staff,
        action="application.transition",
        subject_type="application",
        subject_id=application_id,
        detail={"from": current, "to": body.to, "slots": body.slots},
        ip=client_ip(request),
    )
    logger.info(
        "application %s %s -> %s by %s (%d slot(s) reopened)",
        application_id,
        current,
        body.to,
        staff.staff_id,
        len(body.slots),
    )
    return {"status": body.to, "pending_corrections": body.slots}


def _base_path(key: str) -> str:
    parts = key.split(".")
    if len(parts) == 3 and parts[0] == "child" and parts[1].isdigit():
        return f"child.{parts[2]}"
    return key


# ── the widget review queue (F3) ─────────────────────────────────────────────


class WidgetReview(BaseModel):
    decision: Literal["approved", "rejected"]
    #: An edited payload.
    payload: dict[str, Any] | None = None
    note: str = Field(default="", max_length=1000)


@router.get("/widgets")
async def widget_queue(
    limit: int = 50, staff: Staff = Depends(current_staff)
) -> dict[str, Any]:
    """Candidates, most-served first."""
    from sqlalchemy import text as sql

    from app.db import session

    async with session() as db:
        if db is None:
            raise HTTPException(status_code=503, detail="No database is configured.")
        rows = (
            await db.execute(
                sql(
                    """
                    SELECT id, concept_id, age_band, locale, kind, payload,
                           source_question, generated_at, serve_count
                      FROM concept_widgets
                     WHERE status = 'candidate'
                     ORDER BY serve_count DESC, generated_at ASC
                     LIMIT :limit
                    """
                ),
                {"limit": max(1, min(limit, 200))},
            )
        ).all()

    return {
        "rows": [
            {
                "id": str(row[0]),
                "concept_id": row[1],
                "age_band": row[2],
                "locale": row[3],
                "kind": row[4],
                "payload": row[5],
                "source_question": row[6],
                "generated_at": row[7].isoformat(),
                "serve_count": row[8],
            }
            for row in rows
        ]
    }


@router.post("/widgets/{concept_id}/{age_band}/{locale}")
async def review_widget(
    concept_id: str,
    age_band: str,
    locale: str,
    body: WidgetReview,
    request: Request,
    staff: Staff = Depends(current_staff),
) -> dict[str, Any]:
    """Approve, edit-and-approve, or reject."""
    from app.widgets.cache import CACHE, CacheKey

    payload = body.payload
    if payload is not None:
        import json

        from app.widgets.validate import validate_widget

        result = validate_widget(
            json.dumps(payload), age_band=age_band, locale=locale
        )
        if not result.ok:
            raise HTTPException(
                status_code=400,
                detail=f"That edit does not pass the {result.gate} check: {result.reason}",
            )

    await CACHE.review(
        CacheKey(concept_id, age_band, locale),
        status=body.decision,
        reviewed_by=staff.staff_id,
        payload=payload,
    )
    await audit(
        staff,
        action=f"widget.{body.decision}",
        subject_type="widget",
        subject_id=f"{concept_id}/{age_band}/{locale}",
        detail={"edited": payload is not None, "note": body.note},
        ip=client_ip(request),
    )
    return {"status": body.decision}


# ── sign-in ──────────────────────────────────────────────────────────────────


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=1, max_length=200)


@router.post("/auth/session")
async def sign_in(body: Credentials, request: Request) -> dict[str, Any]:
    """Exchange a staff credential for a staff token."""
    from app.api.admin.staff import sign_in as verify

    result = await verify(body.email, body.password)
    if result is None:
        logger.warning("Failed staff sign-in attempt from %s.", client_ip(request))
        raise HTTPException(status_code=401, detail="Those details do not match.")

    await audit(
        result.staff,
        action="staff.sign_in",
        subject_type="staff",
        subject_id=result.staff.staff_id,
        ip=client_ip(request),
    )
    return {
        "token": result.token,
        "role": result.staff.role,
        "email": result.staff.email,
        # The portal refuses to show the queue until this is cleared, so a seeded temporary password cannot become a pe…
        "must_change_password": result.must_change_password,
    }


@router.post("/auth/password")
async def change_password(
    body: PasswordChange,
    request: Request,
    staff: Staff = Depends(current_staff),
) -> dict[str, Any]:
    """Rotate a password."""
    from app.api.admin.staff import change_password as rotate

    problem = await rotate(staff.staff_id, body.current, body.new)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    await audit(
        staff,
        action="staff.password_changed",
        subject_type="staff",
        subject_id=staff.staff_id,
        ip=client_ip(request),
    )
    # Every token issued under the old password is now dead, including this one.
    from app.api.admin.auth import mint_staff_token

    return {
        "token": mint_staff_token(
            staff_id=staff.staff_id, email=staff.email, role=staff.role
        )
    }


# ── the learning agent's health ──────────────────────────────────────────────


@router.get("/learning/health")
async def learning_health(
    hours: int = 24, staff: Staff = Depends(current_staff)
) -> dict[str, Any]:
    """Six rates, four thresholds, and what breached them."""
    from dataclasses import asdict

    from app.learning import health as learning

    window = max(1, min(hours, learning.RETENTION_HOURS))
    snapshot = await learning.snapshot(window)
    return {
        **asdict(snapshot),
        "healthy": snapshot.healthy,
        "thresholds": {
            "teach_fallback_rate": learning.TEACH_FALLBACK_MAX,
            "widget_drop_rate": learning.WIDGET_GATE_FAILED_MAX,
            "resolution_none_rate": learning.RESOLUTION_NONE_MAX,
            "zero_prose_turns": 0,
        },
    }
