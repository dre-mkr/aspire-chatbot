"""Presigned URLs, so document bytes never touch this process.

The browser asks for a URL, PUTs the file straight to the bucket, and hands the
graph a `document_id`. FastAPI sees a few hundred bytes of JSON; the file itself
never enters a request body we parse, graph state, a log line, or a model
context.

## Why not just accept the upload

Because a 10MB birth certificate posted to this service is a birth certificate
in the request log, in the APM trace, in whatever a crash reporter captured, and
in the worker's memory for the length of the request. Three of those four are
places nobody audited for children's identity documents. Removing the hop
removes all four.

## The signature is the authorisation

The PUT carries no cookie and no bearer token -- deliberately. Sending our
session credential to a storage host would be sending it somewhere it has no
business being, and the signature already scopes the grant to one key, one
method, one content type and a few minutes.

## Private bucket, always

There is no code path here that produces a public URL. Reads go through
`presign_download`, which mints a short-lived signed GET and writes an audit
row -- so "who looked at this child's papers?" is answerable.

## Without S3 credentials this refuses rather than degrades

A registration flow that cannot store a document must say so. The alternative --
accepting the upload through FastAPI as a fallback -- would mean the safe path
is the one that silently stops being used the moment a key is missing.
"""

from __future__ import annotations

import base64
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

#: What a document slot will accept. Checked here as well as in the client,
#: because the client's check is a courtesy and this one is the control.
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
    """Where the object lives.

    Application-scoped and slot-scoped, so a bucket listing is legible and a
    single application's documents can be removed together when retention says
    so. The document id is last and is a UUID, so the key is not guessable from
    the application id alone.
    """
    safe_slot = slot.replace("/", "_").replace("..", "_")
    return f"applications/{application_id}/{safe_slot}/{document_id}"


def check_upload(mime: str, size_bytes: int) -> str | None:
    """Why this upload is refused, or None.

    Runs before a URL is minted. A signature handed out for a 40MB video is a
    signature that will be used for a 40MB video.
    """
    if mime not in ALLOWED_MIME:
        return f"{mime or 'that file type'} is not one we can accept"
    if size_bytes <= 0:
        return "that file is empty"
    if size_bytes > MAX_BYTES:
        return f"that file is larger than {MAX_BYTES // (1024 * 1024)}MB"
    return None


async def owns_application(application_id: str, claims: Any) -> bool:
    """Whether this caller may upload into this application.

    The counterpart to `turn.owns_thread`, and written to the same rules,
    because the failure it prevents is the same one: a resource identifier that
    arrives in a request body and is trusted.

    `applications` carries both halves of an identity -- `session_id` for a draft
    started anonymously and `owner_user_id` once an account is attached -- so a
    caller matches if either matches.

    Fail-closed only where there is something to be closed against:

      * an application id that is the caller's OWN session id is theirs by
        definition; that is the default the endpoint has always used, and it is
        allowed before any row exists;
      * a row that is not there yet belongs to whoever is starting it, exactly as
        a new thread does;
      * a row stored with neither a session nor an owner is unowned and stays
        open, matching `owns_thread`'s treatment of an anonymous thread;
      * a row belonging to somebody ELSE is refused.

    A database that cannot be read does NOT fail open here, and that is the one
    place this deliberately differs from `owns_thread`. Being unable to check
    conversation ownership costs a reader their own history; being unable to
    check application ownership would hand out a signed write into a stranger's
    identity-document folder. The safe default is opposite in the two cases.
    """
    from app.db import database_enabled, session

    # No database means no applications table, so there is nothing this could be
    # granting access to beyond the caller's own session-scoped prefix.
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
        # Not created yet. Only the caller's own session id reaches here, and
        # that was allowed above, so anything else is a guess at somebody's id.
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
    """A URL the browser may PUT one file to, once, soon.

    The content type is part of the signature, so a caller who asked for a JPEG
    upload cannot use the URL to store an executable -- the storage host
    rejects the mismatch.
    """
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
    """A short-lived signed GET, for an admin viewing a document.

    Minted per access rather than stored, and the caller is expected to write an
    audit row alongside -- see `api/admin`. A URL that lives longer than the
    look at it is a URL that outlives the reason it existed.
    """
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


# ── SigV4 ────────────────────────────────────────────────────────────────────
#
# Implemented rather than pulled in with boto3, and the trade is worth naming:
# boto3 is 50MB of dependency for two signatures, and this is the query-string
# form of SigV4, which is about forty lines and is specified precisely. The
# canonical-request construction is the part that has to be exactly right; the
# comments below mark the two places it is easy to get wrong.


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
    # Sorted, and each part percent-encoded with `safe=""`. Both matter: the
    # canonical query string is sorted by encoded key, and a `/` left unescaped
    # in the credential makes the signature differ from the server's.
    canonical_query = "&".join(
        f"{quote(name, safe='')}={quote(query[name], safe='')}"
        for name in sorted(query)
    )

    # Path-style (`endpoint/bucket/key`) or virtual-hosted (`bucket.endpoint/key`),
    # decided by whether the endpoint already names the bucket.
    #
    # This is not a nicety. `S3_ENDPOINT_URL` copied from the AWS console is the
    # virtual-hosted form -- `https://<bucket>.s3.<region>.amazonaws.com` -- and
    # signing that path-style puts the bucket in the URL TWICE. S3 then reads the
    # first path segment as part of the key and the PUT succeeds, writing a real
    # object at `<bucket>/applications/...` while the database row says
    # `applications/...`. Every read of it 404s.
    #
    # That is the same failure `UploadDirective.application_id` exists to prevent,
    # arriving by configuration instead of by code, and it is worse here because
    # nothing in the request fails: only addressing the bucket correctly avoids it.
    #
    # The host may carry a port (MinIO is `localhost:9000`), which is why this
    # tests the leading label rather than the whole host.
    bucket_in_host = host.split(":", 1)[0].startswith(f"{bucket}.")
    path = key if bucket_in_host else f"{bucket}/{key}"

    # The path is encoded WITHOUT escaping `/`, unlike the query. Getting this
    # backwards produces a signature mismatch that reads as an auth failure.
    canonical_uri = "/" + quote(path, safe="/")

    canonical_request = "\n".join(
        [
            method,
            canonical_uri,
            canonical_query,
            canonical_headers,
            header_names,
            # Unsigned payload: the body is the file, and hashing 10MB in this
            # process to sign a URL the browser will use would defeat the point
            # of not handling the file here.
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


def checksum(data: bytes) -> str:
    """Base64 SHA-256, matching what storage returns, for integrity checks."""
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def storage_configured() -> bool:
    """Whether uploads are possible at all. Read by the health endpoint."""
    try:
        _config()
        return True
    except StorageUnavailable:
        return False


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
    """The row to insert once the client says the PUT succeeded.

    `scan_status` is `pending` and there is no argument to override it. A
    document nobody scanned must never be recordable as clean, and the way to
    guarantee that is to make it unsayable here.
    """
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
