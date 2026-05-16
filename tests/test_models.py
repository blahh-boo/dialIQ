"""Schema-level checks for the ORM models (no DB connection required)."""

from __future__ import annotations

from maple.db import (
    AnsweredBy,
    Base,
    CallAttempt,
    CallStatus,
    Extraction,
    Lead,
    Score,
    Tier,
    Transcript,
)

EXPECTED_TABLES = {"leads", "call_attempts", "transcripts", "extractions", "scores"}


def test_all_tables_registered() -> None:
    assert EXPECTED_TABLES.issubset(set(Base.metadata.tables.keys()))


def test_model_table_names() -> None:
    assert Lead.__tablename__ == "leads"
    assert CallAttempt.__tablename__ == "call_attempts"
    assert Transcript.__tablename__ == "transcripts"
    assert Extraction.__tablename__ == "extractions"
    assert Score.__tablename__ == "scores"


def test_partial_unique_index_on_vapi_call_id() -> None:
    indexes = {idx.name: idx for idx in CallAttempt.__table__.indexes}
    idx = indexes["uq_call_attempts_vapi_call_id"]
    assert idx.unique is True
    assert idx.dialect_options["postgresql"]["where"] is not None


def test_lead_phone_e164_is_unique() -> None:
    phone_col = Lead.__table__.c.phone_e164
    assert phone_col.unique is True
    assert phone_col.nullable is False


def test_status_enum_values() -> None:
    assert set(CallStatus) == {
        CallStatus.PENDING,
        CallStatus.IN_PROGRESS,
        CallStatus.COMPLETED,
        CallStatus.FAILED,
    }


def test_answered_by_enum_values() -> None:
    assert set(AnsweredBy) == {
        AnsweredBy.HUMAN,
        AnsweredBy.VOICEMAIL,
        AnsweredBy.IVR,
        AnsweredBy.NO_ANSWER,
        AnsweredBy.BUSY,
    }


def test_tier_enum_values() -> None:
    assert set(Tier) == {Tier.HOT, Tier.WARM, Tier.COLD}
