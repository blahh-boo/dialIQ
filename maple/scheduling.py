"""Campaign scheduling: small composable steps + a thin campaign loop.

`run_campaign` is deliberately a thin orchestrator over named, independently
testable steps, so the who/when/what rules can evolve in isolation:

- WHO     — `get_callable_leads` selects eligible leads.
- WHEN    — `is_callable_now` / `is_callable_at` gate to 11am-2pm local time.
- order   — `next_lead` never dials the same restaurant twice in a row.
- WHAT    — `resolve_order_context` decides the cuisine + item to order.
- build   — `build_call_request` assembles the per-call Vapi payload.
- persist — `record_call_outcome` writes the attempt (+ pipeline for mock/replay).
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
from maple.voice import EndOfCallReport, PlacedCall, VoiceProvider

logger = logging.getLogger(__name__)

_SHOPPER_NAME = "Alex"
_INFERENCE_FALLBACK_CUISINE = "American"
_INFERENCE_FALLBACK_ORDER_ITEM = "cheeseburger and fries"

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


# ── What to order ───────────────────────────────────────────────────────────
def resolve_order_context(lead: Lead, *, client: ClaudeClient) -> tuple[str, str]:
    """Decide *what* to order for this lead: `(cuisine_type, order_item)`.

    Reuses the lead's stored values if already inferred; otherwise infers once
    via Haiku and writes the result back onto the lead (the caller's session
    persists it on flush/commit). If inference fails the lead's fields are left
    untouched — so a later attempt can retry — and a safe default is returned so
    a call is never blocked on inference.
    """
    if lead.cuisine_type and lead.inferred_order_item:
        return lead.cuisine_type, lead.inferred_order_item
    try:
        precall = infer_cuisine_and_order(
            restaurant_name=lead.restaurant_name,
            website=lead.website,
            client=client,
        )
    except Exception:
        logger.warning("Pre-call inference failed for lead %d", lead.id)
        return (
            lead.cuisine_type or _INFERENCE_FALLBACK_CUISINE,
            lead.inferred_order_item or _INFERENCE_FALLBACK_ORDER_ITEM,
        )
    lead.cuisine_type = precall.cuisine_type
    lead.inferred_order_item = precall.order_item
    return precall.cuisine_type, precall.order_item


# ── Call request assembly ───────────────────────────────────────────────────
@dataclass(frozen=True)
class CallRequest:
    """Everything the voice provider needs for one call.

    'What to order' is resolved upstream and frozen here, so call placement is
    pure I/O — no business logic leaks into the provider boundary.
    """

    lead_id: int
    to: str
    assistant_id: str
    variables: dict[str, str]


def build_call_request(
    lead: Lead, *, cuisine_type: str, order_item: str, assistant_id: str
) -> CallRequest:
    """Assemble the per-call Vapi `variableValues` payload for *lead*."""
    return CallRequest(
        lead_id=lead.id,
        to=lead.phone_e164,
        assistant_id=assistant_id,
        variables={
            "shopper_name": _SHOPPER_NAME,
            "restaurant_name": lead.restaurant_name,
            "cuisine_type": cuisine_type or _INFERENCE_FALLBACK_CUISINE,
            "order_item": order_item or _INFERENCE_FALLBACK_ORDER_ITEM,
        },
    )


# ── Campaign loop ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CampaignResult:
    called: int
    skipped_hours: int  # leads skipped — not in business hours right now
    skipped_queue: int  # leads skipped — interleave or exhausted queue


# A call "connected" — we reached someone/something and captured usable data —
# if its extraction classified the line as a human, voicemail, or IVR. Only
# NO_ANSWER / BUSY produce no data and are worth re-dialing.
_CONNECTED_OUTCOMES = (DBAnsweredBy.HUMAN, DBAnsweredBy.VOICEMAIL, DBAnsweredBy.IVR)

# Default dial attempts per lead before giving up (1 = no retry). The live value
# flows from Settings.max_call_attempts via the CLI; this is the direct-call
# fallback for tests / REPL use.
DEFAULT_MAX_CALL_ATTEMPTS = 2


def is_retry_eligible(
    *, attempt_count: int, has_connected: bool, has_in_flight: bool, max_attempts: int
) -> bool:
    """Pure policy: may this lead be (re)dialed, given its call history?

    - A new lead (no attempts) is always eligible.
    - A lead with a call mid-flight (PENDING/IN_PROGRESS) is never re-dialed —
      we wait for it to resolve (for live, the webhook will land the result).
    - A lead that already connected (reached a human/voicemail/IVR) is done —
      the data is captured and re-dialing a real restaurant would be rude.
    - Otherwise (only no-answer/busy/failed attempts) it stays eligible until
      it has used up *max_attempts*.

    Kept pure (no DB) so the callable rules can evolve and be unit-tested in
    isolation from the query that assembles its inputs.
    """
    if has_in_flight or has_connected:
        return False
    return attempt_count < max_attempts


def get_callable_leads(
    session: Session,
    *,
    fetch_limit: int,
    ignore_business_hours: bool = False,
    max_attempts: int = DEFAULT_MAX_CALL_ATTEMPTS,
) -> list[Lead]:
    """Leads eligible to dial now: never-called, or a retryable no-answer/busy
    still under the attempt cap, and (unless *ignore_business_hours*) inside the
    11am-2pm local window.

    Over-fetches by 3x to leave room for the business-hours filter. The per-lead
    decision is delegated to `is_retry_eligible` so the policy stays pure; this
    function only assembles its inputs from the call history.
    """
    counts: dict[int, int] = {}
    in_flight: set[int] = set()
    for row in session.query(CallAttempt.lead_id, CallAttempt.status):
        lead_id = row[0]
        counts[lead_id] = counts.get(lead_id, 0) + 1
        if row[1] in (CallStatus.PENDING, CallStatus.IN_PROGRESS):
            in_flight.add(lead_id)

    connected: set[int] = {
        row[0]
        for row in (
            session.query(CallAttempt.lead_id)
            .join(Extraction, Extraction.call_attempt_id == CallAttempt.id)
            .filter(Extraction.answered_by.in_(_CONNECTED_OUTCOMES))
            .distinct()
        )
    }

    excluded = {
        lead_id
        for lead_id, n in counts.items()
        if not is_retry_eligible(
            attempt_count=n,
            has_connected=lead_id in connected,
            has_in_flight=lead_id in in_flight,
            max_attempts=max_attempts,
        )
    }

    query = session.query(Lead).order_by(Lead.google_reviews_count.desc().nullslast())
    if excluded:
        query = query.filter(Lead.id.notin_(excluded))
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


def record_call_outcome(
    request: CallRequest,
    placed: PlacedCall,
    *,
    session: Session,
    client: ClaudeClient,
) -> None:
    """Persist the `call_attempts` row and, for mock/replay, the transcript +
    extraction pipeline.

    For live providers `placed.report` is None now — the report arrives later
    via the webhook path, which runs the same extraction pipeline there.
    """
    attempt_number = session.query(CallAttempt).filter_by(lead_id=request.lead_id).count() + 1
    report = placed.report
    attempt = CallAttempt(
        lead_id=request.lead_id,
        attempt_number=attempt_number,
        status=CallStatus.COMPLETED if report else CallStatus.IN_PROGRESS,
        vapi_call_id=placed.vapi_call_id,
        # Carry call metadata onto the row. ended_reason/duration come from the
        # report (present for mock fixtures and real calls); started/ended only
        # exist for real Vapi calls (None for canned fixtures, by design).
        ended_reason=report.ended_reason if report else None,
        duration_seconds=report.duration_seconds if report else None,
        started_at=report.started_at if report else None,
        ended_at=report.ended_at if report else None,
    )
    session.add(attempt)
    session.flush()

    if placed.report is None:
        return

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


def run_campaign(
    *,
    limit: int,
    session: Session,
    voice_provider: VoiceProvider,
    client: ClaudeClient,
    assistant_id: str,
    ignore_business_hours: bool = False,
    max_attempts: int = DEFAULT_MAX_CALL_ATTEMPTS,
) -> CampaignResult:
    """Fire up to *limit* mystery-shop calls.

    A thin orchestrator: select → interleave → resolve order → build request →
    place → record. Each step is a named function above; this loop only wires
    them together and tracks counters.

    For mock/replay the full pipeline (classify → extract → score) runs
    synchronously inside `record_call_outcome`; for live it arrives via webhook.

    *ignore_business_hours* bypasses the 11am-2pm gate (mock/replay seeding only).
    *max_attempts* caps re-dials of a no-answer/busy lead (see `is_retry_eligible`).
    """
    candidates = get_callable_leads(
        session,
        fetch_limit=limit * 3,
        ignore_business_hours=ignore_business_hours,
        max_attempts=max_attempts,
    )

    called = 0
    last_called_id: int | None = None
    remaining = list(candidates)

    while called < limit and remaining:
        lead = next_lead(remaining, last_called_id=last_called_id)
        if lead is None:
            break
        remaining.remove(lead)

        cuisine_type, order_item = resolve_order_context(lead, client=client)
        session.flush()  # persist any newly-inferred cuisine before the call

        request = build_call_request(
            lead,
            cuisine_type=cuisine_type,
            order_item=order_item,
            assistant_id=assistant_id,
        )
        placed = voice_provider.place_call(
            to=request.to,
            assistant_id=request.assistant_id,
            variables=request.variables,
        )
        logger.info("Placed call to lead %d — vapi_call_id=%s", lead.id, placed.vapi_call_id)

        record_call_outcome(request, placed, session=session, client=client)

        session.commit()
        last_called_id = lead.id
        called += 1

    return CampaignResult(called=called, skipped_hours=0, skipped_queue=0)
