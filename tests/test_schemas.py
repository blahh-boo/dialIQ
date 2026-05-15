"""Validation tests for the LLM schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mystery_shop.llm.schemas import (
    CallFacts,
    Deduction,
    FieldEvidence,
    ScoreResult,
)
from tests.factories import make_call_facts, make_extraction_metadata


def test_callfacts_round_trips_through_json() -> None:
    facts = make_call_facts()
    rebuilt = CallFacts.model_validate_json(facts.model_dump_json())
    assert rebuilt == facts


def test_callfacts_rejects_unknown_top_level_field() -> None:
    payload = make_call_facts().model_dump()
    payload["surprise"] = "nope"
    with pytest.raises(ValidationError, match="surprise"):
        CallFacts.model_validate(payload)


def test_callfacts_pickup_is_required() -> None:
    payload = make_call_facts().model_dump()
    del payload["pickup"]
    with pytest.raises(ValidationError, match="pickup"):
        CallFacts.model_validate(payload)


def test_callfacts_customer_effort_score_out_of_range() -> None:
    with pytest.raises(ValidationError, match="customer_effort_score"):
        make_call_facts(customer_effort_score=0)
    with pytest.raises(ValidationError, match="customer_effort_score"):
        make_call_facts(customer_effort_score=6)


def test_callfacts_is_immutable() -> None:
    facts = make_call_facts()
    with pytest.raises(ValidationError):
        facts.pickup = False  # type: ignore[misc]


def test_field_evidence_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        FieldEvidence(confidence=1.5, evidence="x")
    with pytest.raises(ValidationError):
        FieldEvidence(confidence=-0.1, evidence="x")
    assert FieldEvidence(confidence=0.0, evidence="x").confidence == 0.0
    assert FieldEvidence(confidence=1.0, evidence="x").confidence == 1.0


def test_field_evidence_evidence_max_length() -> None:
    with pytest.raises(ValidationError):
        FieldEvidence(confidence=0.5, evidence="x" * 501)


def test_extraction_metadata_requires_all_seven_fields() -> None:
    payload = make_extraction_metadata().model_dump()
    del payload["customer_effort_score"]
    with pytest.raises(ValidationError, match="customer_effort_score"):
        type(make_extraction_metadata()).model_validate(payload)


def test_callfacts_rings_to_answer_range() -> None:
    with pytest.raises(ValidationError):
        make_call_facts(rings_to_answer=-1)
    with pytest.raises(ValidationError):
        make_call_facts(rings_to_answer=51)


def test_callfacts_key_failure_quote_max_length() -> None:
    with pytest.raises(ValidationError):
        make_call_facts(key_failure_quote="x" * 501)
    assert make_call_facts(key_failure_quote=None).key_failure_quote is None


def test_score_result_clamps_to_0_100() -> None:
    with pytest.raises(ValidationError):
        ScoreResult(pickup=True, numeric_score=101, tier="COLD", rubric_version="v1")
    with pytest.raises(ValidationError):
        ScoreResult(pickup=True, numeric_score=-1, tier="COLD", rubric_version="v1")


def test_score_result_rejects_unknown_tier() -> None:
    with pytest.raises(ValidationError):
        ScoreResult(
            pickup=True,
            numeric_score=50,
            tier="LUKEWARM",  # type: ignore[arg-type]
            rubric_version="v1",
        )


def test_deduction_points_non_negative() -> None:
    with pytest.raises(ValidationError):
        Deduction(reason="x", points=-1)
    assert Deduction(reason="x", points=0).points == 0


def test_score_result_is_immutable() -> None:
    result = ScoreResult(pickup=True, numeric_score=80, tier="COLD", rubric_version="v1")
    with pytest.raises(ValidationError):
        result.numeric_score = 50  # type: ignore[misc]
