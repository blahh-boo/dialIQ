"""DB-integration smoke test: the schema actually accepts inserts on SQLite.

The rest of the suite is pure-unit and never touches a database — which is
exactly why a SQLite-only bug (a BIGINT PRIMARY KEY is not a rowid alias, so it
never auto-increments) shipped undetected: every `make seed` ran against
Postgres. This test exercises a real insert + the full FK chain on an in-memory
SQLite DB so that whole class of dialect bug fails loudly in CI.
"""

from __future__ import annotations

import sqlalchemy as sa
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
from sqlalchemy.orm import Session


def _memory_db() -> sa.Engine:
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def test_lead_pk_autoincrements_on_sqlite() -> None:
    # With a plain BIGINT PRIMARY KEY this id stays None and the flush raises
    # IntegrityError: NOT NULL constraint failed: leads.id.
    with Session(_memory_db()) as s:
        lead = Lead(restaurant_name="Test", phone_e164="+15555550100")
        s.add(lead)
        s.flush()
        assert lead.id is not None
        s.commit()


def test_server_default_timestamps_populate_on_sqlite() -> None:
    # Guards the created_at/updated_at server defaults against a dialect that
    # lacks the default's SQL function.
    with Session(_memory_db()) as s:
        lead = Lead(restaurant_name="Stamped", phone_e164="+15555550133")
        s.add(lead)
        s.commit()
        assert lead.created_at is not None
        assert lead.updated_at is not None


def test_full_fk_chain_inserts_on_sqlite() -> None:
    with Session(_memory_db()) as s:
        lead = Lead(restaurant_name="Chain", phone_e164="+15555550111")
        s.add(lead)
        s.flush()

        attempt = CallAttempt(lead_id=lead.id, attempt_number=1, status=CallStatus.COMPLETED)
        s.add(attempt)
        s.flush()

        s.add(
            Transcript(
                call_attempt_id=attempt.id,
                raw_jsonb={"messages": []},
                plaintext="hello",
            )
        )
        extraction = Extraction(
            call_attempt_id=attempt.id,
            fields_jsonb={},
            pickup=True,
            answered_by=AnsweredBy.HUMAN,
            model_used="test",
            prompt_version="v0",
        )
        s.add(extraction)
        s.flush()

        s.add(
            Score(
                extraction_id=extraction.id,
                pickup=True,
                numeric_score=100,
                tier=Tier.COLD,
                rubric_version="v2",
            )
        )
        s.commit()

        assert s.query(Score).count() == 1
        assert s.query(Lead).one().id == lead.id
