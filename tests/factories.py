"""Reusable builders for valid Pydantic models in tests.

Not collected as a test module by pytest (no `test_` prefix). Import from here
inside `test_*.py` files when you need a quick valid `CallFacts`.
"""

from __future__ import annotations

from typing import Any

from mystery_shop.llm.schemas import (
    CallFacts,
    ExtractionMetadata,
    FieldEvidence,
)


def make_field_evidence(
    confidence: float = 0.9,
    evidence: str = "Observed directly in transcript.",
) -> FieldEvidence:
    return FieldEvidence(confidence=confidence, evidence=evidence)


def make_extraction_metadata() -> ExtractionMetadata:
    fe = make_field_evidence()
    return ExtractionMetadata(
        rings_to_answer=fe,
        hold_time_seconds=fe,
        transfer_count=fe,
        interruption_count=fe,
        repeated_information_count=fe,
        customer_effort_score=fe,
        key_failure_quote=fe,
    )


def make_call_facts(**overrides: Any) -> CallFacts:
    """Return a valid CallFacts with best-case defaults, overrideable per-field.

    Defaults represent a flawless call (score = 100).
    """
    defaults: dict[str, Any] = {
        "pickup": True,
        "rings_to_answer": 2,
        "put_on_hold": False,
        "hold_time_seconds": None,
        "transfer_count": 0,
        "call_abandoned_by_restaurant": False,
        "interruption_count": 0,
        "repeated_information_count": 0,
        "upsell_attempted": True,
        "customer_effort_score": 1,
        "key_failure_quote": None,
        "extraction_metadata": make_extraction_metadata(),
    }
    defaults.update(overrides)
    return CallFacts.model_validate(defaults)
