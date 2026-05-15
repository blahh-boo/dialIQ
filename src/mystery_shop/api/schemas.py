"""Response schemas for the SDR Cockpit API.

Reuses `CallFacts` and `ScoreResult` from the LLM pipeline — same shapes that
the extractor produces and the rubric scores. The frontend's TS types mirror
these exactly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from mystery_shop.llm.schemas import AnsweredBy, CallFacts, ScoreResult


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
