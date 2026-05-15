"""Sonnet pre-call inference: cuisine_type + order_item from restaurant name + URL."""

from __future__ import annotations

from typing import Any, cast

import anthropic
from pydantic import BaseModel, ConfigDict

from mystery_shop.llm.claude_client import ClaudeClient

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
