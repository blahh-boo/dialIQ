"""Pydantic models for Vapi webhook payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class VapiCustomer(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    number: str


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
    """Vapi's end-of-call-report message (inner message object, not the outer envelope)."""

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    type: Literal["end-of-call-report"]
    call: VapiCallInner
    ended_reason: str = Field(alias="endedReason")
    transcript: str | None = None
    messages: list[VapiTranscriptMessage] = []


class VapiStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: Literal["status-update"]
    call: VapiCallInner
    status: str


class VapiWebhookEnvelope(BaseModel):
    """Outer envelope Vapi always wraps messages in."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    message: dict[str, Any]
