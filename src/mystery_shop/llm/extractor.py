"""Sonnet Pass 2: strict tool-use extraction of 10 CallFacts fields from a transcript."""

from __future__ import annotations

import logging
from typing import Any, cast

import anthropic

logger = logging.getLogger(__name__)

from mystery_shop.llm.claude_client import ClaudeClient
from mystery_shop.llm.schemas import (
    AnsweredBy,
    CallFacts,
    ExtractionMetadata,
    FieldEvidence,
)
from mystery_shop.voice.base import EndOfCallReport

EXTRACTOR_MODEL = "claude-sonnet-4-6"
EXTRACTOR_PROMPT_VERSION = "extractor_v1.txt"

_FIELD_EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "0.0 = no signal in transcript, 1.0 = explicitly stated",
        },
        "evidence": {
            "type": "string",
            "maxLength": 500,
            "description": "Brief quote or note from the transcript supporting this value",
        },
    },
    "required": ["confidence", "evidence"],
    "additionalProperties": False,
}

_EXTRACTOR_TOOL: anthropic.types.ToolParam = {
    "name": "extract_call_facts",
    "description": "Extract structured operational quality facts from a restaurant takeout call transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pickup": {
                "type": "boolean",
                "description": "Did the call connect to any answering party (human, voicemail, IVR)?",
            },
            "rings_to_answer": {
                "anyOf": [
                    {"type": "integer", "minimum": 0, "maximum": 50},
                    {"type": "null"},
                ],
                "description": "Number of rings before answer. null if not discernible.",
            },
            "put_on_hold": {"type": "boolean", "description": "Was the caller placed on hold?"},
            "hold_time_seconds": {
                "anyOf": [
                    {"type": "integer", "minimum": 0, "maximum": 3600},
                    {"type": "null"},
                ],
                "description": "Total hold duration in seconds. null if never put on hold.",
            },
            "transfer_count": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10,
                "description": "Number of times the call was transferred to a different person.",
            },
            "call_abandoned_by_restaurant": {
                "type": "boolean",
                "description": "Did the restaurant hang up before the interaction concluded?",
            },
            "interruption_count": {
                "type": "integer",
                "minimum": 0,
                "maximum": 20,
                "description": "Times the restaurant spoke over or cut off the caller mid-sentence.",
            },
            "repeated_information_count": {
                "type": "integer",
                "minimum": 0,
                "maximum": 20,
                "description": "Times the caller had to repeat the same information.",
            },
            "upsell_attempted": {
                "type": "boolean",
                "description": "Did any staff proactively offer additional items?",
            },
            "customer_effort_score": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "1 = effortless, 5 = very high effort (transfers, repeats, abandonment).",
            },
            "key_failure_quote": {
                "anyOf": [
                    {"type": "string", "maxLength": 500},
                    {"type": "null"},
                ],
                "description": "Verbatim quote from a staff member showing the worst failure. null if smooth.",
            },
            "extraction_metadata": {
                "type": "object",
                "description": "Per-field confidence and evidence for ambiguous numeric fields.",
                "properties": {
                    "rings_to_answer": _FIELD_EVIDENCE_SCHEMA,
                    "hold_time_seconds": _FIELD_EVIDENCE_SCHEMA,
                    "transfer_count": _FIELD_EVIDENCE_SCHEMA,
                    "interruption_count": _FIELD_EVIDENCE_SCHEMA,
                    "repeated_information_count": _FIELD_EVIDENCE_SCHEMA,
                    "customer_effort_score": _FIELD_EVIDENCE_SCHEMA,
                    "key_failure_quote": _FIELD_EVIDENCE_SCHEMA,
                },
                "required": [
                    "rings_to_answer",
                    "hold_time_seconds",
                    "transfer_count",
                    "interruption_count",
                    "repeated_information_count",
                    "customer_effort_score",
                    "key_failure_quote",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "pickup",
            "rings_to_answer",
            "put_on_hold",
            "hold_time_seconds",
            "transfer_count",
            "call_abandoned_by_restaurant",
            "interruption_count",
            "repeated_information_count",
            "upsell_attempted",
            "customer_effort_score",
            "key_failure_quote",
            "extraction_metadata",
        ],
        "additionalProperties": False,
    },
}


def _no_pickup_facts(answered_by: AnsweredBy) -> CallFacts:
    """Return a minimal CallFacts for calls that were never answered by a human."""
    no_signal = FieldEvidence(confidence=0.0, evidence=f"Call not answered ({answered_by})")
    return CallFacts(
        pickup=False,
        rings_to_answer=None,
        put_on_hold=False,
        hold_time_seconds=None,
        transfer_count=0,
        call_abandoned_by_restaurant=False,
        interruption_count=0,
        repeated_information_count=0,
        upsell_attempted=False,
        customer_effort_score=5,
        key_failure_quote=None,
        extraction_metadata=ExtractionMetadata(
            rings_to_answer=no_signal,
            hold_time_seconds=no_signal,
            transfer_count=no_signal,
            interruption_count=no_signal,
            repeated_information_count=no_signal,
            customer_effort_score=no_signal,
            key_failure_quote=no_signal,
        ),
    )


def _parse_tool_input(tool_input: dict[str, Any]) -> CallFacts:
    """Validate and construct CallFacts from the raw tool_use input dict."""
    meta_raw: dict[str, Any] = tool_input["extraction_metadata"]
    metadata = ExtractionMetadata(
        rings_to_answer=FieldEvidence(**meta_raw["rings_to_answer"]),
        hold_time_seconds=FieldEvidence(**meta_raw["hold_time_seconds"]),
        transfer_count=FieldEvidence(**meta_raw["transfer_count"]),
        interruption_count=FieldEvidence(**meta_raw["interruption_count"]),
        repeated_information_count=FieldEvidence(**meta_raw["repeated_information_count"]),
        customer_effort_score=FieldEvidence(**meta_raw["customer_effort_score"]),
        key_failure_quote=FieldEvidence(**meta_raw["key_failure_quote"]),
    )
    return CallFacts(
        pickup=tool_input["pickup"],
        rings_to_answer=tool_input["rings_to_answer"],
        put_on_hold=tool_input["put_on_hold"],
        hold_time_seconds=tool_input["hold_time_seconds"],
        transfer_count=tool_input["transfer_count"],
        call_abandoned_by_restaurant=tool_input["call_abandoned_by_restaurant"],
        interruption_count=tool_input["interruption_count"],
        repeated_information_count=tool_input["repeated_information_count"],
        upsell_attempted=tool_input["upsell_attempted"],
        customer_effort_score=tool_input["customer_effort_score"],
        key_failure_quote=tool_input["key_failure_quote"],
        extraction_metadata=metadata,
    )


def _parse_extractor_response(response: anthropic.types.Message) -> CallFacts:
    """Extract CallFacts from the model's tool_use block."""
    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_call_facts":
            return _parse_tool_input(cast(dict[str, Any], block.input))
    raise ValueError(f"No extract_call_facts tool_use in response: {response.content}")


def extract_call_facts(
    report: EndOfCallReport,
    *,
    answered_by: AnsweredBy,
    client: ClaudeClient,
) -> CallFacts:
    """Run Sonnet extraction on *report*. Skips LLM if call was not answered by a human."""
    if answered_by != "HUMAN":
        return _no_pickup_facts(answered_by)

    system = client.load_prompt(EXTRACTOR_PROMPT_VERSION)
    user_content = (
        f"Call duration: {report.duration_seconds}s\n"
        f"End reason: {report.ended_reason}\n\n"
        f"Transcript:\n{report.transcript_text}"
    )
    response = client.complete_with_tool(
        model=EXTRACTOR_MODEL,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        tool=_EXTRACTOR_TOOL,
        tool_name="extract_call_facts",
        max_tokens=3000,
        temperature=0.0,
    )
    logger.info(
        f"Extractor output tokens: {response.usage.output_tokens} / 3000 "
        f"({100 * response.usage.output_tokens / 3000:.1f}% of limit)"
    )
    return _parse_extractor_response(response)
