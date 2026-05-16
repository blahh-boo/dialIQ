"""REST handlers for the SDR Cockpit frontend.

All endpoints live under `/api/`. Read-only for now (queue + detail). Action
endpoints (dial/email/meeting/sequence/snooze) will follow in a later pass.
"""

from __future__ import annotations

from typing import Any, Literal, cast

import phonenumbers
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm import Session

from maple.db import CallAttempt, Extraction, Lead, Score, Transcript, session_scope
from maple.llm.schemas import CallFacts
from maple.scoring import score_call
from maple.web.models import (
    CampaignStats,
    LeadCallInfo,
    LeadDetailResponse,
    LeadResponse,
    LeadsListResponse,
    MeResponse,
    SdrState,
    TranscriptTurn,
)

router = APIRouter(prefix="/api", tags=["cockpit"])

_TIER_ORDER = {"HOT": 0, "WARM": 1, "COLD": 2}


def _phone_display(e164: str) -> str:
    try:
        parsed = phonenumbers.parse(e164, None)
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
    except phonenumbers.NumberParseException:
        return e164


def _build_lead_response(
    lead: Lead, attempt: CallAttempt, extraction: Extraction, score: Score
) -> LeadResponse:
    facts = CallFacts.model_validate(extraction.fields_jsonb)
    score_result = score_call(facts)

    return LeadResponse(
        id=lead.id,
        restaurant_name=lead.restaurant_name,
        phone_e164=lead.phone_e164,
        phone_display=_phone_display(lead.phone_e164),
        address=lead.address,
        city=lead.city,
        state=lead.state,
        cuisine_type=lead.cuisine_type,
        website=lead.website,
        google_reviews_count=lead.google_reviews_count,
        answered_by=extraction.answered_by.value,
        key_failure_quote=facts.key_failure_quote,
        one_liner=score.summary_one_liner,
        call=LeadCallInfo(
            attempt_id=attempt.id,
            started_at=attempt.started_at,
            duration_seconds=attempt.duration_seconds,
            vapi_call_id=attempt.vapi_call_id,
        ),
        facts=facts,
        score=score_result,
        sdr_state=SdrState(),
    )


def _fetch_latest_per_lead(session: Session) -> list[tuple[Lead, CallAttempt, Extraction, Score]]:
    """Return the latest scored row per lead, joined for display."""
    rows = (
        session.query(Lead, CallAttempt, Extraction, Score)
        .join(CallAttempt, CallAttempt.lead_id == Lead.id)
        .join(Extraction, Extraction.call_attempt_id == CallAttempt.id)
        .join(Score, Score.extraction_id == Extraction.id)
        .all()
    )
    best: dict[int, tuple[Lead, CallAttempt, Extraction, Score]] = {}
    for lead, attempt, extraction, score in rows:
        if lead.id not in best or score.id > best[lead.id][3].id:
            best[lead.id] = (lead, attempt, extraction, score)
    return list(best.values())


@router.get("/leads", response_model=LeadsListResponse)
def list_leads(
    tier: str | None = Query(None, pattern="^(HOT|WARM|COLD)$"),
    q: str | None = Query(None, min_length=1),
) -> LeadsListResponse:
    """Return ranked queue. HOT → WARM → COLD, then numeric_score ASC."""
    with session_scope() as session:
        rows = _fetch_latest_per_lead(session)
        leads = [_build_lead_response(*r) for r in rows]

    if tier:
        leads = [lr for lr in leads if lr.score.tier == tier]
    if q:
        ql = q.lower()
        leads = [
            lr
            for lr in leads
            if ql in lr.restaurant_name.lower()
            or (lr.city or "").lower().startswith(ql)
            or (lr.cuisine_type or "").lower().startswith(ql)
        ]

    leads.sort(
        key=lambda lr: (
            _TIER_ORDER.get(lr.score.tier, 9),
            lr.score.numeric_score,
            -(lr.google_reviews_count or 0),
        )
    )
    return LeadsListResponse(leads=leads)


@router.get("/leads/{lead_id}", response_model=LeadDetailResponse)
def get_lead(lead_id: int) -> LeadDetailResponse:
    with session_scope() as session:
        row = (
            session.query(Lead, CallAttempt, Extraction, Score)
            .join(CallAttempt, CallAttempt.lead_id == Lead.id)
            .join(Extraction, Extraction.call_attempt_id == CallAttempt.id)
            .join(Score, Score.extraction_id == Extraction.id)
            .filter(Lead.id == lead_id)
            .order_by(Score.id.desc())
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"No lead with id {lead_id}")

        lead, attempt, extraction, score = row
        lead_response = _build_lead_response(lead, attempt, extraction, score)

        transcript = session.query(Transcript).filter_by(call_attempt_id=attempt.id).first()
        turns: list[TranscriptTurn] = []
        if transcript and transcript.raw_jsonb:
            for msg in transcript.raw_jsonb.get("messages", []):
                role = _map_role(msg.get("role"))
                if role is None:
                    continue
                turns.append(
                    TranscriptTurn(
                        role=cast(Literal["shopper", "restaurant", "system"], role),
                        text=msg.get("message", ""),
                        t=int(msg.get("time", 0)),
                    )
                )

    return LeadDetailResponse(lead=lead_response, transcript=turns, recording_url=None)


def _map_role(vapi_role: Any) -> str | None:
    """Map transcript role names → frontend role names.

    Our Vapi assistant ("Takeout Order Caller") IS the Maple mystery shopper,
    so role="assistant" is the shopper placing the order and role="user" is the
    restaurant answering. The canned fixtures follow the same convention.
    """
    if vapi_role == "assistant":
        return "shopper"
    if vapi_role == "user":
        return "restaurant"
    if vapi_role == "system":
        return "system"
    return None


@router.get("/me", response_model=MeResponse)
def get_me() -> MeResponse:
    """Hardcoded SDR identity for v1. Replace with real auth later."""
    return MeResponse(id=1, name="Sohail Hajri", initials="SH", email="sohailhajri@gmail.com")


@router.get("/campaign/stats", response_model=CampaignStats)
def campaign_stats() -> CampaignStats:
    """Top-bar campaign metrics. Recomputed per request."""
    with session_scope() as session:
        total_leads = session.query(Lead).count()
        rows = _fetch_latest_per_lead(session)

    if not rows:
        return CampaignStats(
            campaign_name="Round 2",
            total_leads=total_leads,
            mystery_shopped=0,
            avg_score=0,
            hot_count=0,
            no_pickup_count=0,
            touched_today=0,
        )

    scored = [score_call(CallFacts.model_validate(e.fields_jsonb)) for _, _, e, _ in rows]
    avg = sum(s.numeric_score for s in scored) // len(scored)
    hot = sum(1 for s in scored if s.tier == "HOT")
    no_pickup = sum(1 for s in scored if not s.pickup)

    return CampaignStats(
        campaign_name="Round 2",
        total_leads=total_leads,
        mystery_shopped=len(rows),
        avg_score=avg,
        hot_count=hot,
        no_pickup_count=no_pickup,
        touched_today=0,
    )
