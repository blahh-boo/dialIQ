"""Haiku Pass 1: classify how a call was answered before running the expensive extractor."""

from __future__ import annotations

from typing import Any, cast

import anthropic

from mystery_shop.llm.claude_client import ClaudeClient
from mystery_shop.llm.schemas import AnsweredBy

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
    )
    return _parse_classifier_response(response)
