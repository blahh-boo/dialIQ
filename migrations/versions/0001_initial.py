"""Initial schema: leads, call_attempts, transcripts, extractions, scores.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CALL_STATUS_VALUES = ("PENDING", "IN_PROGRESS", "COMPLETED", "FAILED")
ANSWERED_BY_VALUES = ("HUMAN", "VOICEMAIL", "IVR", "NO_ANSWER", "BUSY")
TIER_VALUES = ("HOT", "WARM", "COLD")


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("restaurant_name", sa.String, nullable=False),
        sa.Column("phone_e164", sa.String(20), nullable=False),
        sa.Column("website", sa.String, nullable=True),
        sa.Column("address", sa.String, nullable=True),
        sa.Column("city", sa.String, nullable=True),
        sa.Column("state", sa.String(2), nullable=True),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("cuisine_type", sa.String, nullable=True),
        sa.Column("inferred_order_item", sa.String, nullable=True),
        sa.Column("source_row_index", sa.Integer, nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB, nullable=True),
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
        sa.UniqueConstraint("phone_e164", name="uq_leads_phone_e164"),
    )
    op.create_index("ix_leads_timezone", "leads", ["timezone"])
    op.create_index("ix_leads_state", "leads", ["state"])

    op.create_table(
        "call_attempts",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "lead_id",
            sa.BigInteger,
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer, nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                *CALL_STATUS_VALUES,
                name="call_status",
                native_enum=False,
                length=32,
                create_constraint=True,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("vapi_call_id", sa.String, nullable=True),
        sa.Column("ended_reason", sa.String, nullable=True),
        sa.Column("shopper_name", sa.String, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
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
    )
    op.create_index(
        "uq_call_attempts_vapi_call_id",
        "call_attempts",
        ["vapi_call_id"],
        unique=True,
        postgresql_where=sa.text("vapi_call_id IS NOT NULL"),
    )
    op.create_index(
        "uq_call_attempts_lead_attempt",
        "call_attempts",
        ["lead_id", "attempt_number"],
        unique=True,
    )
    op.create_index("ix_call_attempts_status", "call_attempts", ["status"])
    op.create_index(
        "ix_call_attempts_created_at",
        "call_attempts",
        [sa.text("created_at DESC")],
    )

    op.create_table(
        "transcripts",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "call_attempt_id",
            sa.BigInteger,
            sa.ForeignKey("call_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_jsonb", postgresql.JSONB, nullable=False),
        sa.Column("plaintext", sa.Text, nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR,
            sa.Computed(
                "to_tsvector('english', coalesce(plaintext, ''))",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("call_attempt_id", name="uq_transcripts_call_attempt_id"),
    )
    op.create_index(
        "ix_transcripts_tsv",
        "transcripts",
        ["tsv"],
        postgresql_using="gin",
    )

    op.create_table(
        "extractions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "call_attempt_id",
            sa.BigInteger,
            sa.ForeignKey("call_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fields_jsonb", postgresql.JSONB, nullable=False),
        sa.Column("pickup", sa.Boolean, nullable=False),
        sa.Column(
            "answered_by",
            sa.Enum(
                *ANSWERED_BY_VALUES,
                name="answered_by",
                native_enum=False,
                length=32,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("model_used", sa.String, nullable=False),
        sa.Column("prompt_version", sa.String, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_extractions_call_attempt_created",
        "extractions",
        ["call_attempt_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_extractions_prompt_version", "extractions", ["prompt_version"])

    op.create_table(
        "scores",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "extraction_id",
            sa.BigInteger,
            sa.ForeignKey("extractions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pickup", sa.Boolean, nullable=False),
        sa.Column("numeric_score", sa.Integer, nullable=False),
        sa.Column(
            "tier",
            sa.Enum(
                *TIER_VALUES,
                name="tier",
                native_enum=False,
                length=16,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("summary_one_liner", sa.Text, nullable=True),
        sa.Column("rubric_version", sa.String, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "numeric_score >= 0 AND numeric_score <= 100",
            name="ck_scores_numeric_score_range",
        ),
    )
    op.create_index(
        "uq_scores_extraction_rubric",
        "scores",
        ["extraction_id", "rubric_version"],
        unique=True,
    )
    op.create_index("ix_scores_tier", "scores", ["tier"])
    op.create_index(
        "ix_scores_numeric_score",
        "scores",
        [sa.text("numeric_score DESC")],
    )


def downgrade() -> None:
    op.drop_table("scores")
    op.drop_table("extractions")
    op.drop_table("transcripts")
    op.drop_table("call_attempts")
    op.drop_table("leads")
