"""Shared types and VoiceProvider Protocol for all run modes."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class TranscriptMessage(BaseModel):
    """A single turn from a Vapi call transcript."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    role: str  # "assistant" | "user" | "system" | "tool_call" | "tool_result"
    message: str
    time: float = 0.0
    duration: float | None = None


class EndOfCallReport(BaseModel):
    """Normalized end-of-call data — internal representation derived from Vapi's webhook payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    ended_reason: str
    transcript_text: str
    messages: tuple[TranscriptMessage, ...]
    duration_seconds: int = Field(..., ge=0)


class PlacedCall(BaseModel):
    """Return value from VoiceProvider.place_call().

    For live mode, `report` is None — the end-of-call data arrives later via webhook.
    For mock/replay, `report` is populated synchronously.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    vapi_call_id: str
    report: EndOfCallReport | None = None


@runtime_checkable
class VoiceProvider(Protocol):
    def place_call(
        self,
        *,
        to: str,
        assistant_id: str,
        variables: dict[str, str],
    ) -> PlacedCall: ...
