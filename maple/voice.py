"""Voice layer: the VoiceProvider Protocol, shared IO models, and all three
run-mode providers (mock, replay, live Vapi).

mock/replay read canned transcripts from samples/transcripts/ and return the
report synchronously; live Vapi returns immediately and the report arrives
later via POST /vapi/webhook.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

# samples/transcripts/ lives at the repo root; this module is maple/voice.py,
# so parents[1] is the repo root.
_FIXTURES = Path(__file__).resolve().parents[1] / "samples" / "transcripts"


class TranscriptMessage(BaseModel):
    """A single turn from a Vapi call transcript."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    role: str  # "assistant" | "user" | "system" | "tool_call" | "tool_result"
    message: str
    time: float = 0.0
    duration: float | None = None


class EndOfCallReport(BaseModel):
    """Normalized end-of-call data — internal representation of Vapi's payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    ended_reason: str
    transcript_text: str
    messages: tuple[TranscriptMessage, ...]
    duration_seconds: int = Field(..., ge=0)


class PlacedCall(BaseModel):
    """Return value from VoiceProvider.place_call().

    For live mode, `report` is None — the end-of-call data arrives later via
    webhook. For mock/replay, `report` is populated synchronously.
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


class ReplayProvider:
    """Cycles through transcript JSON files in *transcripts_dir*.

    Each file must be a JSON object matching the EndOfCallReport schema.
    Real call transcripts go in samples/transcripts/ after the first live run.
    """

    def __init__(self, transcripts_dir: Path) -> None:
        files = sorted(transcripts_dir.glob("*.json"))
        if not files:
            raise ValueError(f"No transcript JSON files found in {transcripts_dir}")
        self._files = files
        self._index = 0

    def place_call(
        self,
        *,
        to: str,
        assistant_id: str,
        variables: dict[str, str],
    ) -> PlacedCall:
        path = self._files[self._index % len(self._files)]
        call_number = self._index
        self._index += 1
        data = json.loads(path.read_text())
        report = EndOfCallReport.model_validate(data)
        # Include the call sequence so every placed call gets a UNIQUE id —
        # call_attempts.vapi_call_id is unique-constrained, and a campaign
        # cycles these fixtures many times. The transcript content still cycles.
        return PlacedCall(vapi_call_id=f"replay-{path.stem}-{call_number}", report=report)


class MockProvider:
    """Returns canned transcripts from the repo's sample fixtures, no network.

    Identical wire behavior to ReplayProvider; kept as a distinct class so
    RUN_MODE=mock remains a documented choice (no network, CI-deterministic).
    """

    def __init__(self) -> None:
        self._inner = ReplayProvider(transcripts_dir=_FIXTURES)

    def place_call(
        self,
        *,
        to: str,
        assistant_id: str,
        variables: dict[str, str],
    ) -> PlacedCall:
        placed = self._inner.place_call(to=to, assistant_id=assistant_id, variables=variables)
        return PlacedCall(
            vapi_call_id=placed.vapi_call_id.replace("replay-", "mock-", 1),
            report=placed.report,
        )


class VapiProvider:
    """Initiates outbound calls via Vapi. Outcome arrives via POST /vapi/webhook."""

    def __init__(self, *, api_key: str, phone_number_id: str) -> None:
        from vapi import Vapi  # lazy: keeps `import maple.voice` cheap for mock/CI

        self._client = Vapi(token=api_key)
        self._phone_number_id = phone_number_id

    def place_call(
        self,
        *,
        to: str,
        assistant_id: str,
        variables: dict[str, str],  # Protocol signature; widened below for Vapi SDK
    ) -> PlacedCall:
        """Dial *to* using Vapi. Returns immediately; report arrives via webhook."""
        from vapi.types import AssistantOverrides, CreateCustomerDto

        call = self._client.calls.create(
            assistant_id=assistant_id,
            phone_number_id=self._phone_number_id,
            customer=CreateCustomerDto(number=to),
            assistant_overrides=AssistantOverrides(variable_values=dict(variables)),
        )
        return PlacedCall(vapi_call_id=call.id or "", report=None)
