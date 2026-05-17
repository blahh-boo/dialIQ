"""Pydantic models for the web layer.

Two groups:
- Vapi webhook payloads (incoming `end-of-call-report` / `status-update`).
- SDR Cockpit API responses. `LeadResponse.facts`/`score` reuse the LLM
  pipeline's own `CallFacts`/`ScoreResult` — the frontend plugs into the
  same shapes the extractor and rubric produce.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from maple.llm.schemas import AnsweredBy, CallFacts, ScoreResult

# ── Vapi webhook payloads ───────────────────────────────────────────────────


class VapiCustomer(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    # Optional: a failed/early-terminated call's report can omit the customer.
    # We'd rather store the attempt with a missing number than drop it entirely.
    number: str | None = None


class VapiCallInner(BaseModel):
    """Subset of Vapi's call object we care about."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    customer: VapiCustomer
    started_at: datetime | None = Field(None, alias="startedAt")
    ended_at: datetime | None = Field(None, alias="endedAt")


class VapiTranscriptMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    role: str
    message: str
    time: float = 0.0
    duration: float | None = None


class VapiEndOfCallReport(BaseModel):
    """Vapi's end-of-call-report message (inner message object, not the envelope).

    Fields are defaulted defensively: a real sparse payload (failed call,
    early hangup) should still validate and be stored, not silently dropped.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    type: Literal["end-of-call-report"]
    call: VapiCallInner
    ended_reason: str = Field(default="", alias="endedReason")
    transcript: str | None = None
    messages: list[VapiTranscriptMessage] = []
    # Vapi hosts the recording and puts a URL in the payload. Depending on
    # config it's at top-level `recordingUrl` or nested under `artifact`.
    recording_url: str | None = Field(default=None, alias="recordingUrl")
    artifact: dict[str, Any] | None = None

    @property
    def resolved_recording_url(self) -> str | None:
        """The recording URL from whichever location Vapi used."""
        if self.recording_url:
            return self.recording_url
        if self.artifact:
            url = self.artifact.get("recordingUrl") or self.artifact.get("recording_url")
            return url if isinstance(url, str) else None
        return None


class VapiStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: Literal["status-update"]
    call: VapiCallInner
    status: str


class VapiWebhookEnvelope(BaseModel):
    """Outer envelope Vapi always wraps messages in."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    message: dict[str, Any]


# ── SDR Cockpit API responses ───────────────────────────────────────────────


class LeadCallInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: int
    started_at: datetime | None
    duration_seconds: int | None
    vapi_call_id: str | None


class SdrState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dialed_today: bool = False
    contacted_today: bool = False
    snoozed_until: datetime | None = None


class LeadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    restaurant_name: str
    phone_e164: str
    phone_display: str
    address: str | None
    city: str | None
    state: str | None
    cuisine_type: str | None
    website: str | None
    google_reviews_count: int | None
    answered_by: AnsweredBy
    key_failure_quote: str | None
    one_liner: str | None
    call: LeadCallInfo
    facts: CallFacts
    score: ScoreResult
    sdr_state: SdrState


class LeadsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leads: list[LeadResponse]


class TranscriptTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["shopper", "restaurant", "system"]
    text: str
    t: int


class LeadDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead: LeadResponse
    transcript: list[TranscriptTurn]
    recording_url: str | None


class MeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    initials: str
    email: str


class CampaignStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_name: str
    total_leads: int
    mystery_shopped: int
    avg_score: int
    hot_count: int
    no_pickup_count: int
    touched_today: int
