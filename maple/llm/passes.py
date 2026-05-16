"""The three short Claude passes around the heavy extractor:

- `infer_cuisine_and_order` — Sonnet, pre-call: cuisine + a plausible order.
- `classify_answered_by` — Haiku, post-call pass 1: HUMAN/VOICEMAIL/IVR/…
- `generate_one_liner` — Haiku, post-score: the ≤25-word SDR brief.

The big 10-field extraction lives in `extractor.py`.
"""

from __future__ import annotations

from typing import Any, cast

import anthropic
from pydantic import BaseModel, ConfigDict

from maple.llm.client import ClaudeClient
from maple.llm.schemas import AnsweredBy, CallFacts, ScoreResult

# ── Pre-call inference (Sonnet) ─────────────────────────────────────────────
PRECALL_MODEL = "claude-sonnet-4-6"
PRECALL_PROMPT_VERSION = "precall_v1.txt"

_PRECALL_TOOL: anthropic.types.ToolParam = {
    "name": "infer_cuisine_and_order",
    "description": "Infer a restaurant's cuisine type and a plausible takeout order item.",
    "input_schema": {
        "type": "object",
        "properties": {
            "cuisine_type": {
                "type": "string",
                "maxLength": 50,
                "description": (
                    "The restaurant's primary cuisine. E.g. 'Chinese', 'Italian', 'Mexican', "
                    "'American', 'Pizza', 'Indian', 'Thai', 'Japanese', 'Seafood', 'BBQ'."
                ),
            },
            "order_item": {
                "type": "string",
                "maxLength": 100,
                "description": (
                    "A specific, realistic takeout item. E.g. 'General Tso\\'s chicken with fried rice', "
                    "'margherita pizza', 'chicken tikka masala with naan'."
                ),
            },
        },
        "required": ["cuisine_type", "order_item"],
        "additionalProperties": False,
    },
}


class PreCallResult(BaseModel):
    """Inferred cuisine + order item for a single lead."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cuisine_type: str
    order_item: str


def _parse_precall_response(response: anthropic.types.Message) -> PreCallResult:
    for block in response.content:
        if block.type == "tool_use" and block.name == "infer_cuisine_and_order":
            data = cast(dict[str, Any], block.input)
            return PreCallResult(**data)
    raise ValueError(f"No infer_cuisine_and_order tool_use in response: {response.content}")


def infer_cuisine_and_order(
    *,
    restaurant_name: str,
    website: str | None,
    client: ClaudeClient,
) -> PreCallResult:
    """Infer cuisine_type + order_item for a lead using the pre-call Sonnet prompt."""
    system = client.load_prompt(PRECALL_PROMPT_VERSION)
    url_line = f"Website: {website}" if website else "Website: (none)"
    user_content = f"Restaurant name: {restaurant_name}\n{url_line}"

    response = client.complete_with_tool(
        model=PRECALL_MODEL,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        tool=_PRECALL_TOOL,
        tool_name="infer_cuisine_and_order",
        max_tokens=128,
    )
    return _parse_precall_response(response)


# ── Answered-by classifier (Haiku, post-call pass 1) ────────────────────────
CLASSIFIER_MODEL = "claude-haiku-4-5"
CLASSIFIER_PROMPT_VERSION = "classifier_v1.txt"

_CLASSIFIER_TOOL: anthropic.types.ToolParam = {
    "name": "classify_call",
    "description": "Report how the restaurant phone call was answered.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answered_by": {
                "type": "string",
                "enum": ["HUMAN", "VOICEMAIL", "IVR", "NO_ANSWER", "BUSY"],
                "description": (
                    "HUMAN = live person answered; VOICEMAIL = recorded outgoing message; "
                    "IVR = automated press-1 system; NO_ANSWER = rang with no pickup; "
                    "BUSY = busy signal."
                ),
            }
        },
        "required": ["answered_by"],
        "additionalProperties": False,
    },
}


def _parse_classifier_response(response: anthropic.types.Message) -> AnsweredBy:
    """Extract AnsweredBy from the model's tool_use block."""
    for block in response.content:
        if block.type == "tool_use" and block.name == "classify_call":
            tool_input = cast(dict[str, Any], block.input)
            return cast(AnsweredBy, tool_input["answered_by"])
    raise ValueError(f"No classify_call tool_use in response: {response.content}")


def classify_answered_by(transcript_text: str, *, client: ClaudeClient) -> AnsweredBy:
    """Run the Haiku classifier on *transcript_text* and return an AnsweredBy literal."""
    system = client.load_prompt(CLASSIFIER_PROMPT_VERSION)
    response = client.complete_with_tool(
        model=CLASSIFIER_MODEL,
        system=system,
        messages=[{"role": "user", "content": transcript_text}],
        tool=_CLASSIFIER_TOOL,
        tool_name="classify_call",
        max_tokens=64,
        temperature=0.0,
    )
    return _parse_classifier_response(response)


# ── SDR one-liner (Haiku, post-score) ───────────────────────────────────────
SUMMARIZER_MODEL = "claude-haiku-4-5"
SUMMARIZER_PROMPT_VERSION = "summarizer_v1.txt"


def generate_one_liner(
    facts: CallFacts,
    result: ScoreResult,
    *,
    client: ClaudeClient,
) -> str:
    """Return a ≤25-word SDR one-liner for this call result."""
    system = client.load_prompt(SUMMARIZER_PROMPT_VERSION)

    deduction_lines = "\n".join(f"- {d.reason} (-{d.points})" for d in result.deductions)
    user_content = (
        f"tier: {result.tier}\n"
        f"score: {result.numeric_score}/100\n"
        f"pickup: {facts.pickup}\n"
        f"answered_by: (see facts)\n"
        f"put_on_hold: {facts.put_on_hold}\n"
        f"hold_time_seconds: {facts.hold_time_seconds}\n"
        f"transfer_count: {facts.transfer_count}\n"
        f"call_abandoned_by_restaurant: {facts.call_abandoned_by_restaurant}\n"
        f"interruption_count: {facts.interruption_count}\n"
        f"repeated_information_count: {facts.repeated_information_count}\n"
        f"customer_effort_score: {facts.customer_effort_score}/5\n"
        f"key_failure_quote: {facts.key_failure_quote!r}\n"
        f"\ndeductions:\n{deduction_lines or '(none)'}"
    )

    response = client.complete(
        model=SUMMARIZER_MODEL,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        max_tokens=80,
        temperature=0.0,
    )

    for block in response.content:
        if block.type == "text":
            return block.text.strip()

    return f"{result.tier}: Score {result.numeric_score}/100."
