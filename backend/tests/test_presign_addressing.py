"""The signed URL must point at the key the database will record."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

import pytest

from app.storage.presign import _sign, storage_key_for

KEY = storage_key_for(
    "11111111-2222-3333-4444-555555555555",
    "guardian.id_document",
    "583356a1f3514313a7ed04e5b9ab3d69",
)


def _path(endpoint: str, bucket: str) -> str:
    url = _sign(
        method="GET",
        endpoint=endpoint,
        bucket=bucket,
        region="us-east-2",
        key=KEY,
        key_id="AKIASTUBSTUBSTUBSTUB",
        secret="stub-not-a-real-credential",
        ttl=900,
    )
    return unquote(urlparse(url).path)


class TestTheUrlPointsWhereTheRowPoints:
    def test_a_virtual_hosted_endpoint_does_not_repeat_the_bucket(self):
        """The bug, as configured in this project's own .env."""
        path = _path("https://aspire-chatbot.s3.us-east-2.amazonaws.com", "aspire-chatbot")

        assert path == f"/{KEY}"
        assert "aspire-chatbot/aspire-chatbot" not in path
        assert path.count("aspire-chatbot") == 0, (
            "the bucket is already in the hostname; repeating it in the path "
            "writes the object one prefix deeper than the row records"
        )

    def test_a_path_style_endpoint_still_carries_the_bucket(self):
        """The other half. MinIO and the regional S3 endpoints need this form."""
        path = _path("https://s3.us-east-2.amazonaws.com", "aspire-chatbot")

        assert path == f"/aspire-chatbot/{KEY}"

    def test_a_minio_endpoint_with_a_port_is_path_style(self):
        """`localhost:9000` must not be mistaken for a virtual-hosted host."""
        assert _path("http://localhost:9000", "aspire-documents") == (
            f"/aspire-documents/{KEY}"
        )

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://aspire-chatbot.s3.us-east-2.amazonaws.com",
            "https://s3.us-east-2.amazonaws.com",
            "http://localhost:9000",
        ],
    )
    def test_the_object_key_s3_derives_is_the_recorded_key(self, endpoint):
        """The invariant that actually matters, stated once for every style."""
        bucket = "aspire-chatbot"
        host = urlparse(_sign(
            method="GET",
            endpoint=endpoint,
            bucket=bucket,
            region="us-east-2",
            key=KEY,
            key_id="AKIASTUBSTUBSTUBSTUB",
            secret="stub-not-a-real-credential",
            ttl=900,
        )).netloc
        path = _path(endpoint, bucket).lstrip("/")

        if host.split(":", 1)[0].startswith(f"{bucket}."):
            object_key = path
        else:
            assert path.startswith(f"{bucket}/"), "path-style must name the bucket"
            object_key = path[len(bucket) + 1 :]

        assert object_key == KEY
