"""Presigned URLs, so document bytes never touch this process."""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from app.config import get_settings

logger = logging.getLogger(__name__)

#: What a document slot will accept.
ALLOWED_MIME: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/heic", "image/webp", "application/pdf"}
)

MAX_BYTES = 10 * 1024 * 1024


class StorageUnavailable(RuntimeError):
    """No object storage is configured. Registration cannot accept documents."""


@dataclass(frozen=True, slots=True)
class Presigned:
    url: str
    document_id: str
    storage_key: str
    headers: dict[str, str]
    expires_at: datetime


def _config() -> tuple[str, str, str, str, str]:
    settings = get_settings()
    if not (settings.s3_access_key_id and settings.s3_secret_access_key):
        raise StorageUnavailable(
            "S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY are unset, so documents "
            "cannot be stored. Registration refuses rather than routing file "
            "bytes through the application."
        )
    endpoint = (settings.s3_endpoint_url or "https://s3.amazonaws.com").rstrip("/")
    return (
        endpoint,
        settings.s3_bucket,
        settings.s3_region,
        settings.s3_access_key_id,
        settings.s3_secret_access_key,
    )


def storage_key_for(application_id: str, slot: str, document_id: str) -> str:
    """Where the object lives."""
    safe_slot = slot.replace("/", "_").replace("..", "_")
    return f"applications/{application_id}/{safe_slot}/{document_id}"


def check_upload(mime: str, size_bytes: int) -> str | None:
    """Why this upload is refused, or None."""
    if mime not in ALLOWED_MIME:
        return f"{mime or 'that file type'} is not one we can accept"
    if size_bytes <= 0:
        return "that file is empty"
    if size_bytes > MAX_BYTES:
        return f"that file is larger than {MAX_BYTES // (1024 * 1024)}MB"
    return None


async def owns_application(application_id: str, claims: Any) -> bool:
    """Whether this caller may upload into this application."""
    from app.db import database_enabled, session

    # No database means no applications table, so the caller's own session id is all there is.
    if not database_enabled():
        return application_id == str(getattr(claims, "session_id", ""))

    session_id = str(getattr(claims, "session_id", "") or "")
    user_id = getattr(claims, "user_id", None)

    if application_id == session_id and session_id:
        return True

    from sqlalchemy import text as sql

    try:
        async with session() as db:
            if db is None:
                return application_id == session_id
            row = (
                await db.execute(
                    sql(
                        "SELECT session_id, owner_user_id FROM applications "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {"id": application_id},
                )
            ).first()
    except Exception:
        # Includes a malformed id, which never matches a real application.
        logger.warning(
            "Could not check ownership of application %s; refusing.",
            application_id,
            exc_info=True,
        )
        return False

    if row is None:
        # Not created yet.
        return False

    row_session, row_owner = row
    if row_session is None and row_owner is None:
        return True
    if row_session is not None and str(row_session) == session_id and session_id:
        return True
    if row_owner is not None and user_id is not None and str(row_owner) == str(user_id):
        return True
    return False


def presign_upload(
    *,
    application_id: str,
    slot: str,
    mime: str,
    size_bytes: int,
    ttl_seconds: int | None = None,
) -> Presigned:
    """A URL the browser may PUT one file to, once, soon."""
    problem = check_upload(mime, size_bytes)
    if problem:
        raise ValueError(problem)

    endpoint, bucket, region, key_id, secret = _config()
    settings = get_settings()
    ttl = ttl_seconds or settings.s3_url_ttl_seconds

    document_id = uuid.uuid4().hex
    key = storage_key_for(application_id, slot, document_id)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)

    url = _sign(
        method="PUT",
        endpoint=endpoint,
        bucket=bucket,
        region=region,
        key=key,
        key_id=key_id,
        secret=secret,
        ttl=ttl,
        signed_headers={"content-type": mime},
    )

    logger.info(
        "presigned upload application=%s slot=%s mime=%s bytes=%d",
        application_id,
        slot,
        mime,
        size_bytes,
    )
    return Presigned(
        url=url,
        document_id=document_id,
        storage_key=key,
        headers={"Content-Type": mime},
        expires_at=expires_at,
    )


def presign_download(storage_key: str, *, ttl_seconds: int | None = None) -> str:
    """A short-lived signed GET, for an admin viewing a document."""
    endpoint, bucket, region, key_id, secret = _config()
    ttl = ttl_seconds or get_settings().s3_url_ttl_seconds
    return _sign(
        method="GET",
        endpoint=endpoint,
        bucket=bucket,
        region=region,
        key=storage_key,
        key_id=key_id,
        secret=secret,
        ttl=ttl,
    )


# ── SigV4 ──
# Implemented here rather than pulling in an AWS SDK for one signature.


def _sign(
    *,
    method: str,
    endpoint: str,
    bucket: str,
    region: str,
    key: str,
    key_id: str,
    secret: str,
    ttl: int,
    signed_headers: dict[str, str] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    day = now.strftime("%Y%m%d")

    host = endpoint.split("://", 1)[-1]
    scope = f"{day}/{region}/s3/aws4_request"

    headers = {"host": host, **(signed_headers or {})}
    header_names = ";".join(sorted(headers))
    canonical_headers = "".join(
        f"{name}:{headers[name].strip()}\n" for name in sorted(headers)
    )

    query = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{key_id}/{scope}",
        "X-Amz-Date": stamp,
        "X-Amz-Expires": str(ttl),
        "X-Amz-SignedHeaders": header_names,
    }
    # Sorted, and each part percent-encoded with `safe=""`.
    canonical_query = "&".join(
        f"{quote(name, safe='')}={quote(query[name], safe='')}"
        for name in sorted(query)
    )

    # Path-style or virtual-hosted, decided by whether the endpoint host already names the bucket.
    bucket_in_host = host.split(":", 1)[0].startswith(f"{bucket}.")
    path = key if bucket_in_host else f"{bucket}/{key}"

    # The path is encoded WITHOUT escaping `/`, unlike the query.
    canonical_uri = "/" + quote(path, safe="/")

    canonical_request = "\n".join(
        [
            method,
            canonical_uri,
            canonical_query,
            canonical_headers,
            header_names,
            # Unsigned payload: the file bytes never pass through this process.
            "UNSIGNED-PAYLOAD",
        ]
    )

    to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            stamp,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )

    signing_key = _derive(secret, day, region)
    signature = hmac.new(signing_key, to_sign.encode(), hashlib.sha256).hexdigest()

    return f"{endpoint}{canonical_uri}?{canonical_query}&X-Amz-Signature={signature}"


def _derive(secret: str, day: str, region: str) -> bytes:
    def step(key: bytes, message: str) -> bytes:
        return hmac.new(key, message.encode(), hashlib.sha256).digest()

    return step(step(step(step(f"AWS4{secret}".encode(), day), region), "s3"), "aws4_request")


def document_record(
    *,
    document_id: str,
    application_id: str,
    slot: str,
    storage_key: str,
    mime: str,
    size_bytes: int,
    uploaded_by: str | None,
) -> dict[str, Any]:
    """The row to insert once the client says the PUT succeeded."""
    return {
        "id": document_id,
        "application_id": application_id,
        "slot": slot,
        "storage_key": storage_key,
        "mime": mime,
        "size_bytes": size_bytes,
        "uploaded_by": uploaded_by,
        "scan_status": "pending",
    }
