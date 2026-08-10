"""The admin API: the queue, one application, the status machine, the widget queue.

Mounted at `/api/admin`, on the same FastAPI app as the chat but behind its own
auth realm (`admin/auth.py`). Same process, same database, different door.

The `/api` prefix is load-bearing, not decoration. The portal's own pages are
TanStack routes at `/admin`, `/admin/applications` and `/admin/widgets`, and in
production nginx serves the app and this API from ONE hostname. While this
router sat at `/admin`, `GET /admin/applications` was two different things --
the HTML page and this JSON list -- and nginx had no way to tell them apart.
Whichever upstream won, the other broke. Keep the API under `/api/`, where the
single proxy rule in deploy/nginx-aspire.conf already sends it to uvicorn.

## F2's status machine is the highest-value thing here

    submitted → under_review → info_requested → under_review → approved
                                                             → rejected

Two rules, and both are enforced in this file and in the schema:

  1. **Every transition needs a reason note.** `review_events.reason` is NOT
     NULL with a non-empty check. A queue whose transitions can be unexplained
     is a queue nobody can audit three months later when a family asks why.

  2. **`info_requested` names the SPECIFIC slots.** Those slot paths go onto
     `applications.pending_corrections`, the parent's chat reopens exactly
     those, collects them, and resubmits. The parent does not refill the form.

That second rule is what turns a rejection into a conversation. The alternative
-- "some details were incorrect, please start again" -- is how applications die.

## Nothing here returns an unmasked PII value in a list

The queue returns masked display values. The detail view returns the real ones,
and it writes an audit row before it does. That asymmetry is deliberate: a list
is glanced at by many people many times, and a detail view is opened on purpose.
"""

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

#: The only moves the machine allows. A dict of sets rather than a chain of
#: conditionals, because "can this go from X to Y?" is the question people ask
#: of this file and a table answers it by being read.
TRANSITIONS: dict[str, frozenset[str]] = {
    "submitted": frozenset({"under_review"}),
    "under_review": frozenset({"info_requested", "approved", "rejected"}),
    # Back to review only. An application whose corrections have landed is
    # re-reviewed; it does not jump straight to approved, because the point of
    # asking was to look again.
    "info_requested": frozenset({"under_review"}),
    # Terminal. Reopening an approved or rejected application is a new
    # application, not a transition -- otherwise the audit trail of a decision
    # can be rewritten after the fact.
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
    #: How many documents `doc_check` flagged. The queue sorts can use it; the
    #: flag itself is advisory and never decides anything.
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
    """The review queue. Oldest first, because that is the fair order.

    Default sort is age of application ascending -- a family who applied in
    March is seen before one who applied last week, whatever else is true about
    the rows. A queue sorted by anything else needs a reason, and "newest
    first" is not one.
    """
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
    """Fields on the left, documents on the right. One call, both halves.

    One call rather than two, because the reviewer's job IS the comparison --
    making them fetch the documents separately means a tab switch, and F1 exists
    to remove exactly that.

    Decrypts the PII, and writes the audit row BEFORE returning it. Auditing
    afterwards would miss the case where the response fails to serialise, which
    is the one time it matters that somebody's decrypt happened.
    """
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
    """A short-lived signed URL, and an audit row for having asked.

    The audit row is written before the URL is minted. A download that is
    audited afterwards is a download that is not audited if anything between
    fails -- and this is the one access where that matters most.
    """
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
    """Move an application, with a reason, and reopen slots if asked.

    `info_requested` with no slots is refused. A reviewer who wants corrections
    without saying which ones is asking the parent to guess, which is the
    behaviour this whole loop exists to replace.
    """
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
                # Cleared on every transition that is not info_requested, so a
                # corrected application does not carry its old flags forward.
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
    #: An edited payload. Approving with one writes an override, which is how a
    #: staff member fixes a caption without an engineer touching a prompt.
    payload: dict[str, Any] | None = None
    note: str = Field(default="", max_length=1000)


@router.get("/widgets")
async def widget_queue(
    limit: int = 50, staff: Staff = Depends(current_staff)
) -> dict[str, Any]:
    """Candidates, most-served first.

    Sorted by `serve_count` so the widget a thousand children saw is reviewed
    before the one that ran twice. Returns the PAYLOAD, and the admin UI renders
    it with the real components -- raw JSON is a debugging surface, not a review
    surface, and asking a non-technical reviewer to approve JSON is asking them
    to approve something they cannot read.
    """
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
    """Approve, edit-and-approve, or reject.

    An edited payload is re-validated before it is stored. A reviewer fixing a
    caption cannot accidentally introduce a banned word for the band, or a
    control that breaks gate 4 -- the same seven gates run, and a failure is
    reported to them rather than saved.
    """
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
    """Exchange a staff credential for a staff token.

    One failure message for every cause -- wrong email, wrong password,
    disabled account. Distinguishing them tells anybody probing which addresses
    are real staff accounts, which is the first half of a targeted attack on a
    queue of children's documents.

    The failure is NOT audited with the attempted email. An audit table that
    records every string somebody typed into a login box is an audit table full
    of attacker-controlled text, and the useful signal (the rate) is in the
    application log where it belongs.
    """
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
        # The portal refuses to show the queue until this is cleared, so a
        # seeded temporary password cannot become a permanent one.
        "must_change_password": result.must_change_password,
    }


@router.post("/auth/password")
async def change_password(
    body: PasswordChange,
    request: Request,
    staff: Staff = Depends(current_staff),
) -> dict[str, Any]:
    """Rotate a password. The current one is required even when signed in.

    A staff token on a shared desk is exactly the case this guards: holding the
    token must not be enough to lock its owner out of their own account.
    """
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
    # Every token issued under the old password is now dead, including this
    # one. Returning a fresh one means the person who just changed their
    # password is not signed out for having done the right thing.
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
    """Six rates, four thresholds, and what breached them.

    `breaches` is computed server-side rather than left to whoever reads the
    numbers. A dashboard where the thresholds live in somebody's head is a
    dashboard that agrees with everybody, and the four thresholds here came from
    the Track L brief for reasons that are written down next to them in
    `app/learning/health.py`.

    `zero_prose_turns` has no rate and no tolerance. A learning turn that emitted
    no lesson is the defect this workstream closed; one occurrence is a
    regression rather than a statistic.
    """
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
