"""Database layer: engine, session, declarative Base, the 5 ORM models, and
schema bootstrap.

Schema overview:
    leads ──< call_attempts ──< extractions ──< scores
                       └──── transcripts (1:1)

`init_db()` builds the whole schema from the models in one call (replaces
Alembic — the DB is disposable/local; `make seed` rebuilds it).
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import Any

import sqlalchemy as sa
from sqlalchemy import JSON, Engine, ForeignKey, Index, create_engine, event, text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from maple.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# Portable big-integer key type. Renders as BIGINT on Postgres (the documented
# production swap) but INTEGER on SQLite. SQLite only auto-increments a column
# declared exactly `INTEGER PRIMARY KEY`; a plain `BIGINT PRIMARY KEY` is *not*
# a rowid alias, so `id` would stay NULL on insert and every row would fail the
# NOT NULL constraint. Used for every PK and FK so both dialects stay correct.
BigIntKey = sa.BigInteger().with_variant(sa.Integer, "sqlite")


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the cached SQLAlchemy engine.

    SQLite is the default (zero-install local demo). For SQLite we allow
    cross-thread use (FastAPI background tasks) and turn on foreign-key
    enforcement so ``ON DELETE CASCADE`` works for `reset`.
    """
    url = get_settings().database_url
    is_sqlite = url.startswith("sqlite")
    engine = create_engine(
        url,
        pool_pre_ping=True,
        future=True,
        connect_args={"check_same_thread": False} if is_sqlite else {},
    )

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_conn: Any, _: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            # WAL mode allows concurrent readers + one writer without blocking.
            # Without it, any second process (e.g. `make call` while `make api`
            # is running) hits "database is locked" immediately.
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def upsert_insert() -> Any:
    """The dialect's INSERT that supports ON CONFLICT (the only construct that
    isn't dialect-portable). Callers target conflicts with `index_elements=`
    (column names), which is identical syntax on both dialects — so a Postgres
    swap needs no call-site changes, only this dispatch.
    """
    if get_engine().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )


def get_session() -> Session:
    """Return a new SQLAlchemy session bound to the cached engine."""
    return _session_factory()()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Yield a session that commits on success and rolls back on exception."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create every table from the ORM models. Idempotent (`checkfirst`).

    Replaces Alembic: the schema's single source of truth is the models below,
    and the local DB is disposable. To change the schema: edit a model, then
    `rm -f maple.db && make setup` (or drop/recreate if on the Postgres swap).
    """
    Base.metadata.create_all(get_engine())


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

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
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
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
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

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        BigIntKey,
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
            # Partial unique index: idempotent webhook dedupe, but many rows
            # legitimately have NULL vapi_call_id. Both dialects support this.
            postgresql_where=text("vapi_call_id IS NOT NULL"),
            sqlite_where=text("vapi_call_id IS NOT NULL"),
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

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
    call_attempt_id: Mapped[int] = mapped_column(
        BigIntKey,
        ForeignKey("call_attempts.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    raw_jsonb: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    plaintext: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    call_attempt: Mapped[CallAttempt] = relationship(back_populates="transcript")


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
    call_attempt_id: Mapped[int] = mapped_column(
        BigIntKey,
        ForeignKey("call_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    fields_jsonb: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
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

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True)
    extraction_id: Mapped[int] = mapped_column(
        BigIntKey,
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
