"""Applications, encrypted PII, documents, review events and the audit log Revision ID: 0014_applications Revise…"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_applications"
down_revision: str | None = "0013_concept_widgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("owner_user_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        # How a parent gets back in three days later, from another device.
        sa.Column("resume_token", sa.Text(), nullable=False),
        # Non-sensitive answers only.
        sa.Column(
            "answers",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # The slot paths a reviewer flagged.
        sa.Column(
            "pending_corrections",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("consent_version", sa.Text(), nullable=True),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attested_ip", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('draft','submitted','under_review','info_requested',"
            "'approved','rejected')",
            name="ck_applications_status",
        ),
        # An attested application must know what it attested to.
        sa.CheckConstraint(
            "attested_at is null or consent_version is not null",
            name="ck_applications_consent_version",
        ),
    )
    op.create_index("uq_applications_resume", "applications", ["resume_token"], unique=True)
    # The reviewer's queue: by status, oldest first. Indexed as it is read.
    op.create_index("ix_applications_queue", "applications", ["status", "created_at"])
    op.create_index("ix_applications_session", "applications", ["session_id"])

    op.create_table(
        "application_pii",
        sa.Column(
            "application_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # The slot path: "guardian.national_id", "child.0.date_of_birth".
        sa.Column("slot", sa.Text(), primary_key=True),
        sa.Column("value_encrypted", sa.LargeBinary(), nullable=False),
        # Which key version encrypted it, so a key rotation is a background re-encrypt rather than a data loss.
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "application_children",
        sa.Column(
            "application_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("child_index", sa.Integer(), primary_key=True),
        # Non-sensitive fields only, same split as `applications.answers`.
        sa.Column(
            "answers",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("complete", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "documents_uploaded",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "application_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slot", sa.Text(), nullable=False),
        # The object key in a PRIVATE bucket. Not a URL, and not pasteable.
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=True),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploaded_by", sa.Text(), nullable=True),
        # No `clean` default. Unscanned must not look scanned.
        sa.Column("scan_status", sa.Text(), nullable=False, server_default="pending"),
        # doc_check's advisory verdict.
        sa.Column("check_confidence", sa.Float(), nullable=True),
        sa.Column("check_notes", sa.Text(), nullable=True),
        sa.Column("retakes_requested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scan_status in ('pending','clean','infected','failed')",
            name="ck_documents_scan_status",
        ),
        # One retake, ever. E3's rule, in the schema.
        sa.CheckConstraint("retakes_requested <= 1", name="ck_documents_one_retake"),
    )
    op.create_index(
        "ix_documents_application", "documents_uploaded", ["application_id", "slot"]
    )

    op.create_table(
        "review_events",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "application_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        # NOT NULL and no default.
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "slots_flagged",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_review_reason_present"),
    )
    op.create_index(
        "ix_review_events_application", "review_events", ["application_id", "created_at"]
    )

    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            sa.dialects.postgresql.BIGINT(),
            sa.Identity(always=False),
            primary_key=True,
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("actor_role", sa.Text(), nullable=True),
        # "application.view", "document.download", "widget.approve", "application.transition".
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column(
            "detail",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Document access is queried separately from record views, because the two answer different questions and only…
    op.create_index(
        "ix_audit_documents",
        "audit_log",
        ["subject_id", "created_at"],
        postgresql_where=sa.text("subject_type = 'document'"),
    )
    op.create_index("ix_audit_actor", "audit_log", ["actor", "created_at"])
    op.create_index("ix_audit_subject", "audit_log", ["subject_type", "subject_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_subject", table_name="audit_log")
    op.drop_index("ix_audit_actor", table_name="audit_log")
    op.drop_index("ix_audit_documents", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_review_events_application", table_name="review_events")
    op.drop_table("review_events")
    op.drop_index("ix_documents_application", table_name="documents_uploaded")
    op.drop_table("documents_uploaded")
    op.drop_table("application_children")
    op.drop_table("application_pii")
    op.drop_index("ix_applications_session", table_name="applications")
    op.drop_index("ix_applications_queue", table_name="applications")
    op.drop_index("uq_applications_resume", table_name="applications")
    op.drop_table("applications")
