"""Thin wrapper around the Anthropic SDK with prompt caching on system prompts."""

from __future__ import annotations

from pathlib import Path

import anthropic

_PROMPTS_DIR = Path(__file__).parent / "prompts"


# Bound a single request so one stalled connection can't wedge a whole
# sequential campaign. The SDK default is a 10-minute timeout with retries on
# top; with ~4 LLM calls per shopped call that lets one bad network moment hang
# the run for the better part of an hour. 120s comfortably covers a slow Sonnet
# extraction while turning an indefinite hang into a fast, loud failure.
_REQUEST_TIMEOUT_SECONDS = 120.0
_MAX_RETRIES = 2


class ClaudeClient:
    def __init__(self, api_key: str) -> None:
        self._client = anthropic.Anthropic(
            api_key=api_key,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            max_retries=_MAX_RETRIES,
        )

    @staticmethod
    def load_prompt(filename: str) -> str:
        """Read a versioned prompt file from the prompts directory."""
        return (_PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()

    def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[anthropic.types.MessageParam],
        max_tokens: int = 1024,
        temperature: float = 1.0,
    ) -> anthropic.types.Message:
        """Send a plain completion request (no tools)."""
        return self._client.messages.create(
            model=model,
            system=self._cached_system(system),
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def complete_with_tool(
        self,
        *,
        model: str,
        system: str,
        messages: list[anthropic.types.MessageParam],
        tool: anthropic.types.ToolParam,
        tool_name: str,
        max_tokens: int = 1024,
        temperature: float = 1.0,
    ) -> anthropic.types.Message:
        """Force the model to call *tool_name* using strict tool-choice."""
        return self._client.messages.create(
            model=model,
            system=self._cached_system(system),
            messages=messages,
            tools=[tool],
            tool_choice=anthropic.types.ToolChoiceToolParam(type="tool", name=tool_name),
            max_tokens=max_tokens,
            temperature=temperature,
        )

    @staticmethod
    def _cached_system(text: str) -> list[anthropic.types.TextBlockParam]:
        return [
            anthropic.types.TextBlockParam(
                type="text",
                text=text,
                cache_control=anthropic.types.CacheControlEphemeralParam(type="ephemeral"),
            )
        ]
