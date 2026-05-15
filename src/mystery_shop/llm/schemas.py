"""Pydantic schemas for LLM extraction outputs and downstream scoring.

`CallFacts` is the 10-field canonical extraction shape consumed by the deterministic
scorer. Every field is either directly scored (fields 1-10) or a verbatim SDR hook
(`key_failure_quote`). Per-field confidence + evidence live in `ExtractionMetadata`.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

TierLiteral = Literal["HOT", "WARM", "COLD"]

AnsweredBy = Literal["HUMAN", "VOICEMAIL", "IVR", "NO_ANSWER", "BUSY"]

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class FieldEvidence(BaseModel):
    """Confidence + supporting quote/note for a single extracted field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confidence: Confidence = Field(
        ...,
        description="0.0 = no signal in transcript, 1.0 = explicitly stated.",
    )
    evidence: str = Field(
        ...,
        description="Brief quote or note from the transcript supporting this value.",
        max_length=500,
    )


class ExtractionMetadata(BaseModel):
    """Per-field confidence + evidence for non-boolean extracted fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rings_to_answer: FieldEvidence
    hold_time_seconds: FieldEvidence
    transfer_count: FieldEvidence
    interruption_count: FieldEvidence
    repeated_information_count: FieldEvidence
    customer_effort_score: FieldEvidence
    key_failure_quote: FieldEvidence


class CallFacts(BaseModel):
    """10-field extraction output from a single restaurant call transcript.

    Fields 1-10 are scored by rubric.py. `key_failure_quote` is observation-only
    and surfaces in the SDR one-liner but carries no numeric weight.
    `customer_effort_score`: 1 = effortless, 5 = extremely high effort.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # 1-10: scored by rubric.py
    pickup: bool = Field(..., description="Did a human or system pick up? Load-bearing.")
    rings_to_answer: int | None = Field(None, ge=0, le=50)
    put_on_hold: bool
    hold_time_seconds: int | None = Field(None, ge=0, le=3600)
    transfer_count: int = Field(..., ge=0, le=10)
    call_abandoned_by_restaurant: bool
    interruption_count: int = Field(..., ge=0, le=20)
    repeated_information_count: int = Field(..., ge=0, le=20)
    upsell_attempted: bool
    customer_effort_score: int = Field(
        ...,
        ge=1,
        le=5,
        description="1 = effortless (immediate answer, smooth order), 5 = very high effort (transfers, repeats, confusion).",
    )

    # SDR hook: verbatim quote, not scored
    key_failure_quote: str | None = Field(None, max_length=500)

    extraction_metadata: ExtractionMetadata


class Deduction(BaseModel):
    """A single point deduction applied by the rubric. Preserved for explainability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: str
    points: int = Field(..., ge=0)


class ScoreResult(BaseModel):
    """Deterministic scoring output. Pure function of `CallFacts`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pickup: bool
    numeric_score: int = Field(..., ge=0, le=100)
    tier: TierLiteral
    deductions: tuple[Deduction, ...] = ()
    rubric_version: str
