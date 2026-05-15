"""SQLAlchemy ORM models for Mystery Shop.

Schema overview:
    leads ──< call_attempts ──< extractions ──< scores
                       └──── transcripts (1:1)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mystery_shop.db.session import Base


class CallStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AnsweredBy(StrEnum):
    HUMAN = "HUMAN"
    VOICEMAIL = "VOICEMAIL"
    IVR = "IVR"
    NO_ANSWER = "NO_ANSWER"
    BUSY = "BUSY"


class Tier(StrEnum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    restaurant_name: Mapped[str] = mapped_column(sa.String, nullable=False)
    phone_e164: Mapped[str] = mapped_column(sa.String(20), unique=True, nullable=False)
    website: Mapped[str | None] = mapped_column(sa.String)
    address: Mapped[str | None] = mapped_column(sa.String)
    city: Mapped[str | None] = mapped_column(sa.String)
    state: Mapped[str | None] = mapped_column(sa.String(2))
    postal_code: Mapped[str | None] = mapped_column(sa.String(20))
    timezone: Mapped[str | None] = mapped_column(sa.String(64))
    cuisine_type: Mapped[str | None] = mapped_column(sa.String)
    inferred_order_item: Mapped[str | None] = mapped_column(sa.String)
    google_reviews_count: Mapped[int | None] = mapped_column(sa.Integer)
    source_row_index: Mapped[int | None] = mapped_column(sa.Integer)
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    attempts: Mapped[list[CallAttempt]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_leads_timezone", "timezone"),
        Index("ix_leads_state", "state"),
    )


class CallAttempt(Base):
    __tablename__ = "call_attempts"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[CallStatus] = mapped_column(
        sa.Enum(CallStatus, name="call_status", native_enum=False, length=32),
        nullable=False,
        default=CallStatus.PENDING,
    )
    vapi_call_id: Mapped[str | None] = mapped_column(sa.String)
    ended_reason: Mapped[str | None] = mapped_column(sa.String)
    shopper_name: Mapped[str | None] = mapped_column(sa.String)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(sa.Integer)
    error_message: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    lead: Mapped[Lead] = relationship(back_populates="attempts")
    transcript: Mapped[Transcript | None] = relationship(
        back_populates="call_attempt", cascade="all, delete-orphan", uselist=False
    )
    extractions: Mapped[list[Extraction]] = relationship(
        back_populates="call_attempt", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uq_call_attempts_vapi_call_id",
            "vapi_call_id",
            unique=True,
            postgresql_where=text("vapi_call_id IS NOT NULL"),
        ),
        Index(
            "uq_call_attempts_lead_attempt",
            "lead_id",
            "attempt_number",
            unique=True,
        ),
        Index("ix_call_attempts_status", "status"),
        Index("ix_call_attempts_created_at", sa.desc("created_at")),
    )


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    call_attempt_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        ForeignKey("call_attempts.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    raw_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    plaintext: Mapped[str] = mapped_column(sa.Text, nullable=False)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        sa.Computed("to_tsvector('english', coalesce(plaintext, ''))", persisted=True),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    call_attempt: Mapped[CallAttempt] = relationship(back_populates="transcript")

    __table_args__ = (Index("ix_transcripts_tsv", "tsv", postgresql_using="gin"),)


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    call_attempt_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        ForeignKey("call_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    fields_jsonb: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    pickup: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    answered_by: Mapped[AnsweredBy] = mapped_column(
        sa.Enum(AnsweredBy, name="answered_by", native_enum=False, length=32),
        nullable=False,
    )
    model_used: Mapped[str] = mapped_column(sa.String, nullable=False)
    prompt_version: Mapped[str] = mapped_column(sa.String, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(sa.Integer)
    output_tokens: Mapped[int | None] = mapped_column(sa.Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 6))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    call_attempt: Mapped[CallAttempt] = relationship(back_populates="extractions")
    scores: Mapped[list[Score]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "ix_extractions_call_attempt_created",
            "call_attempt_id",
            sa.desc("created_at"),
        ),
        Index("ix_extractions_prompt_version", "prompt_version"),
    )


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    extraction_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        ForeignKey("extractions.id", ondelete="CASCADE"),
        nullable=False,
    )
    pickup: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    numeric_score: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    tier: Mapped[Tier] = mapped_column(
        sa.Enum(Tier, name="tier", native_enum=False, length=16),
        nullable=False,
    )
    summary_one_liner: Mapped[str | None] = mapped_column(sa.Text)
    rubric_version: Mapped[str] = mapped_column(sa.String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    extraction: Mapped[Extraction] = relationship(back_populates="scores")

    __table_args__ = (
        Index(
            "uq_scores_extraction_rubric",
            "extraction_id",
            "rubric_version",
            unique=True,
        ),
        Index("ix_scores_tier", "tier"),
        Index("ix_scores_numeric_score", sa.desc("numeric_score")),
    )
