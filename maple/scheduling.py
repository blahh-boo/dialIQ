"""Campaign scheduling: business-hours gate, interleave, and the campaign loop.

- `is_callable_now` / `is_callable_at` — only dial during 11am-2pm local time.
- `next_lead` — never call the same restaurant twice in a row.
- `run_campaign` — pick eligible leads, place calls, run the pipeline, persist.
"""

from __future__ import annotations

import logging
import zoneinfo
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from maple.db import (
    AnsweredBy as DBAnsweredBy,
)
from maple.db import (
    CallAttempt,
    CallStatus,
    Extraction,
    Lead,
    Score,
    Transcript,
)
from maple.llm.client import ClaudeClient
from maple.llm.extractor import EXTRACTOR_MODEL, EXTRACTOR_PROMPT_VERSION, extract_call_facts
from maple.llm.passes import classify_answered_by, generate_one_liner, infer_cuisine_and_order
from maple.scoring import RUBRIC_VERSION, score_call
from maple.voice import EndOfCallReport, VoiceProvider

logger = logging.getLogger(__name__)

_SHOPPER_NAME = "Alex"

# ── Business hours ──────────────────────────────────────────────────────────
# Call window: 11:00 AM - 2:00 PM local time (restaurant's timezone).
# Approximation is intentional — state-level tz resolution; ±1h is fine.
CALL_OPEN_HOUR = 11  # 11:00 AM local
CALL_CLOSE_HOUR = 14  # 2:00 PM local (exclusive → last eligible start is 1:59 PM)


def is_callable_now(timezone_name: str | None) -> bool:
    """True if the current local time in *timezone_name* is within the call window."""
    if not timezone_name:
        return False
    try:
        tz = zoneinfo.ZoneInfo(timezone_name)
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        return False
    local = datetime.now(tz)
    return CALL_OPEN_HOUR <= local.hour < CALL_CLOSE_HOUR


def is_callable_at(timezone_name: str | None, when: datetime) -> bool:
    """True if *when* (tz-aware) falls inside the call window for *timezone_name*."""
    if not timezone_name:
        return False
    try:
        tz = zoneinfo.ZoneInfo(timezone_name)
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        return False
    local = when.astimezone(tz)
    return CALL_OPEN_HOUR <= local.hour < CALL_CLOSE_HOUR


# ── Interleave ──────────────────────────────────────────────────────────────
def next_lead(candidates: list[Lead], *, last_called_id: int | None) -> Lead | None:
    """Return the first lead in *candidates* that is not *last_called_id*.

    Falls back to the first candidate if every remaining lead is the same as the
    last (e.g., only one lead left in the queue).
    """
    if not candidates:
        return None
    for lead in candidates:
        if lead.id != last_called_id:
            return lead
    return candidates[0]


# ── Campaign loop ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CampaignResult:
    called: int
    skipped_hours: int  # leads skipped — not in business hours right now
    skipped_queue: int  # leads skipped — interleave or exhausted queue


def get_callable_leads(
    session: Session, *, fetch_limit: int, ignore_business_hours: bool = False
) -> list[Lead]:
    """Leads that have never been called and are in business hours right now.

    Over-fetches by 3x to leave room for business-hours filtering. When
    *ignore_business_hours* is True the time-of-day gate is skipped entirely —
    used for mock/replay seeding, where no real restaurant is dialed.
    """
    already_called_ids = [row[0] for row in session.query(CallAttempt.lead_id).distinct().all()]
    query = session.query(Lead).order_by(Lead.google_reviews_count.desc().nullslast())
    if already_called_ids:
        query = query.filter(Lead.id.notin_(already_called_ids))
    candidates: list[Lead] = query.limit(fetch_limit).all()
    if ignore_business_hours:
        return candidates
    return [lead for lead in candidates if is_callable_now(lead.timezone)]


def _persist_extraction(
    report: EndOfCallReport,
    call_attempt_id: int,
    *,
    session: Session,
    client: ClaudeClient,
) -> None:
    """Classify → extract → score → write extraction + score rows."""
    answered_by = classify_answered_by(report.transcript_text, client=client)
    facts = extract_call_facts(report, answered_by=answered_by, client=client)
    result = score_call(facts)

    try:
        one_liner = generate_one_liner(facts, result, client=client)
    except Exception:
        logger.warning("One-liner generation failed for call_attempt %d", call_attempt_id)
        one_liner = None

    extraction = Extraction(
        call_attempt_id=call_attempt_id,
        fields_jsonb=facts.model_dump(mode="json"),
        pickup=facts.pickup,
        answered_by=DBAnsweredBy(answered_by),
        model_used=EXTRACTOR_MODEL,
        prompt_version=EXTRACTOR_PROMPT_VERSION,
    )
    session.add(extraction)
    session.flush()

    session.add(
        Score(
            extraction_id=extraction.id,
            pickup=result.pickup,
            numeric_score=result.numeric_score,
            tier=result.tier,
            summary_one_liner=one_liner,
            rubric_version=RUBRIC_VERSION,
        )
    )


def run_campaign(
    *,
    limit: int,
    session: Session,
    voice_provider: VoiceProvider,
    client: ClaudeClient,
    assistant_id: str,
    ignore_business_hours: bool = False,
) -> CampaignResult:
    """Fire up to *limit* mystery-shop calls.

    For mock/replay providers the full pipeline (classify → extract → score) runs
    synchronously. For live providers, the report arrives later via webhook.

    *ignore_business_hours* bypasses the 11am-2pm gate (mock/replay seeding only).
    """
    candidates = get_callable_leads(
        session, fetch_limit=limit * 3, ignore_business_hours=ignore_business_hours
    )

    called = skipped_hours = skipped_queue = 0
    last_called_id: int | None = None
    remaining = list(candidates)

    while called < limit and remaining:
        lead = next_lead(remaining, last_called_id=last_called_id)
        if lead is None:
            break
        remaining.remove(lead)

        # Pre-call inference: update lead's cuisine + order_item if not set
        cuisine_type = lead.cuisine_type
        order_item = lead.inferred_order_item
        if not cuisine_type or not order_item:
            try:
                precall = infer_cuisine_and_order(
                    restaurant_name=lead.restaurant_name,
                    website=lead.website,
                    client=client,
                )
                cuisine_type = precall.cuisine_type
                order_item = precall.order_item
                lead.cuisine_type = cuisine_type
                lead.inferred_order_item = order_item
                session.flush()
            except Exception:
                logger.warning("Pre-call inference failed for lead %d", lead.id)
                cuisine_type = cuisine_type or "American"
                order_item = order_item or "cheeseburger and fries"

        variables: dict[str, str] = {
            "shopper_name": _SHOPPER_NAME,
            "restaurant_name": lead.restaurant_name,
            "cuisine_type": cuisine_type or "American",
            "order_item": order_item or "cheeseburger and fries",
        }

        placed = voice_provider.place_call(
            to=lead.phone_e164,
            assistant_id=assistant_id,
            variables=variables,
        )
        logger.info("Placed call to lead %d — vapi_call_id=%s", lead.id, placed.vapi_call_id)

        attempt_number = session.query(CallAttempt).filter_by(lead_id=lead.id).count() + 1
        status = CallStatus.COMPLETED if placed.report else CallStatus.IN_PROGRESS
        attempt = CallAttempt(
            lead_id=lead.id,
            attempt_number=attempt_number,
            status=status,
            vapi_call_id=placed.vapi_call_id,
        )
        session.add(attempt)
        session.flush()

        if placed.report is not None:
            raw_msgs: list[dict[str, Any]] = [m.model_dump() for m in placed.report.messages]
            session.add(
                Transcript(
                    call_attempt_id=attempt.id,
                    raw_jsonb={"messages": raw_msgs, "ended_reason": placed.report.ended_reason},
                    plaintext=placed.report.transcript_text,
                )
            )
            session.flush()
            try:
                _persist_extraction(placed.report, attempt.id, session=session, client=client)
            except Exception:
                logger.exception("Extraction failed for call_attempt %d", attempt.id)

        session.commit()
        last_called_id = lead.id
        called += 1

    return CampaignResult(called=called, skipped_hours=skipped_hours, skipped_queue=skipped_queue)
