"""Tests for LLM extraction parsing — no network required."""

from __future__ import annotations

from typing import Any

import pytest
from maple.llm.extractor import (
    EXTRACTOR_PROMPT_VERSION,
    _no_pickup_facts,
    _parse_tool_input,
)
from maple.llm.schemas import AnsweredBy, CallFacts

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_tool_input(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
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
        "extraction_metadata": {
            "rings_to_answer": {"confidence": 0.9, "evidence": "Rang twice before pickup"},
            "hold_time_seconds": {"confidence": 0.0, "evidence": "Never placed on hold"},
            "transfer_count": {"confidence": 1.0, "evidence": "No transfers mentioned"},
            "interruption_count": {"confidence": 1.0, "evidence": "No interruptions"},
            "repeated_information_count": {"confidence": 1.0, "evidence": "No repeats"},
            "customer_effort_score": {"confidence": 0.9, "evidence": "Smooth order, prompt answer"},
            "key_failure_quote": {"confidence": 0.0, "evidence": "No failures observed"},
        },
    }
    base.update(overrides)
    return base


# ── _parse_tool_input ─────────────────────────────────────────────────────────


def test_parse_tool_input_returns_call_facts() -> None:
    facts = _parse_tool_input(_make_tool_input())
    assert isinstance(facts, CallFacts)


def test_parse_tool_input_pickup_true() -> None:
    facts = _parse_tool_input(_make_tool_input(pickup=True))
    assert facts.pickup is True


def test_parse_tool_input_pickup_false() -> None:
    facts = _parse_tool_input(_make_tool_input(pickup=False))
    assert facts.pickup is False


def test_parse_tool_input_rings() -> None:
    facts = _parse_tool_input(_make_tool_input(rings_to_answer=3))
    assert facts.rings_to_answer == 3


def test_parse_tool_input_rings_none() -> None:
    facts = _parse_tool_input(_make_tool_input(rings_to_answer=None))
    assert facts.rings_to_answer is None


def test_parse_tool_input_hold() -> None:
    facts = _parse_tool_input(_make_tool_input(put_on_hold=True, hold_time_seconds=90))
    assert facts.put_on_hold is True
    assert facts.hold_time_seconds == 90


def test_parse_tool_input_transfer() -> None:
    facts = _parse_tool_input(_make_tool_input(transfer_count=2))
    assert facts.transfer_count == 2


def test_parse_tool_input_abandoned() -> None:
    facts = _parse_tool_input(_make_tool_input(call_abandoned_by_restaurant=True))
    assert facts.call_abandoned_by_restaurant is True


def test_parse_tool_input_ces_bounds() -> None:
    facts_low = _parse_tool_input(_make_tool_input(customer_effort_score=1))
    facts_high = _parse_tool_input(_make_tool_input(customer_effort_score=5))
    assert facts_low.customer_effort_score == 1
    assert facts_high.customer_effort_score == 5


def test_parse_tool_input_key_failure_quote() -> None:
    facts = _parse_tool_input(_make_tool_input(key_failure_quote="We're busy, goodbye."))
    assert facts.key_failure_quote == "We're busy, goodbye."


def test_parse_tool_input_metadata_evidence() -> None:
    facts = _parse_tool_input(_make_tool_input())
    assert facts.extraction_metadata.rings_to_answer.confidence == 0.9
    assert "twice" in facts.extraction_metadata.rings_to_answer.evidence


def test_parse_tool_input_all_metadata_fields_present() -> None:
    facts = _parse_tool_input(_make_tool_input())
    meta = facts.extraction_metadata
    assert meta.rings_to_answer is not None
    assert meta.hold_time_seconds is not None
    assert meta.transfer_count is not None
    assert meta.interruption_count is not None
    assert meta.repeated_information_count is not None
    assert meta.customer_effort_score is not None
    assert meta.key_failure_quote is not None


def test_parse_tool_input_invalid_ces_raises() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _parse_tool_input(_make_tool_input(customer_effort_score=6))


def test_parse_tool_input_invalid_transfer_raises() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _parse_tool_input(_make_tool_input(transfer_count=11))


# ── _no_pickup_facts ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("answered_by", ["VOICEMAIL", "IVR", "NO_ANSWER", "BUSY"])
def test_no_pickup_facts_pickup_false(answered_by: AnsweredBy) -> None:
    facts = _no_pickup_facts(answered_by)
    assert facts.pickup is False


def test_no_pickup_facts_ces_is_max() -> None:
    facts = _no_pickup_facts("VOICEMAIL")
    assert facts.customer_effort_score == 5


def test_no_pickup_facts_zeros() -> None:
    facts = _no_pickup_facts("NO_ANSWER")
    assert facts.transfer_count == 0
    assert facts.interruption_count == 0
    assert facts.repeated_information_count == 0


def test_no_pickup_facts_metadata_mentions_answered_by() -> None:
    facts = _no_pickup_facts("VOICEMAIL")
    assert "VOICEMAIL" in facts.extraction_metadata.rings_to_answer.evidence


def test_no_pickup_facts_metadata_zero_confidence() -> None:
    facts = _no_pickup_facts("BUSY")
    assert facts.extraction_metadata.customer_effort_score.confidence == 0.0


# ── prompt version constant ───────────────────────────────────────────────────


def test_extractor_prompt_version_file_exists() -> None:
    from pathlib import Path

    prompts_dir = Path(__file__).parent.parent / "maple" / "llm" / "prompts"
    assert (prompts_dir / EXTRACTOR_PROMPT_VERSION).exists()


def test_classifier_prompt_version_file_exists() -> None:
    from pathlib import Path

    from maple.llm.passes import CLASSIFIER_PROMPT_VERSION

    prompts_dir = Path(__file__).parent.parent / "maple" / "llm" / "prompts"
    assert (prompts_dir / CLASSIFIER_PROMPT_VERSION).exists()
