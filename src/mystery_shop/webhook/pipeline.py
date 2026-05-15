"""End-of-call extraction pipeline: classify → extract → score → persist."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from mystery_shop.db.models import (
    AnsweredBy as DBAnsweredBy,
)
from mystery_shop.db.models import (
    CallAttempt,
    CallStatus,
    Extraction,
    Lead,
    Score,
    Transcript,
)
from mystery_shop.llm.classifier import classify_answered_by
from mystery_shop.llm.claude_client import ClaudeClient
from mystery_shop.llm.extractor import (
    EXTRACTOR_MODEL,
    EXTRACTOR_PROMPT_VERSION,
    extract_call_facts,
)
from mystery_shop.llm.schemas import AnsweredBy
from mystery_shop.llm.summarizer import generate_one_liner
from mystery_shop.scoring.rubric import RUBRIC_VERSION, score_call
from mystery_shop.voice.base import EndOfCallReport, TranscriptMessage
from mystery_shop.webhook.vapi_models import VapiEndOfCallReport

logger = logging.getLogger(__name__)


def run_extraction_pipeline(
    report: VapiEndOfCallReport,
    call_attempt_id: int,
    *,
    session: Session,
    client: ClaudeClient,
) -> None:
    """Classify → extract → score, then persist extraction + score rows.

    Safe to call multiple times — duplicate extractions are stored for auditing.
    The scores table has a unique constraint on (extraction_id, rubric_version).
    """
    transcript_text = report.transcript or ""

    # Pass 1: cheap Haiku classifier
    answered_by: AnsweredBy = classify_answered_by(transcript_text, client=client)
    logger.info("call_attempt=%d answered_by=%s", call_attempt_id, answered_by)

    # Pass 2: Sonnet extraction (skipped for non-human)
    facts = extract_call_facts(
        _build_end_of_call_report(report),
        answered_by=answered_by,
        client=client,
    )

    # Pass 3: deterministic scoring
    result = score_call(facts)

    # Pass 4: Haiku SDR one-liner
    try:
        one_liner: str | None = generate_one_liner(facts, result, client=client)
    except Exception:
        logger.warning("One-liner generation failed for call_attempt %d", call_attempt_id)
        one_liner = None

    # Persist extraction
    extraction = Extraction(
        call_attempt_id=call_attempt_id,
        fields_jsonb=facts.model_dump(mode="json"),
        pickup=facts.pickup,
        answered_by=DBAnsweredBy(answered_by),
        model_used=EXTRACTOR_MODEL,
        prompt_version=EXTRACTOR_PROMPT_VERSION,
    )
    session.add(extraction)
    session.flush()  # get extraction.id

    score = Score(
        extraction_id=extraction.id,
        pickup=result.pickup,
        numeric_score=result.numeric_score,
        tier=result.tier,
        summary_one_liner=one_liner,
        rubric_version=RUBRIC_VERSION,
    )
    session.add(score)
    session.commit()

    logger.info(
        "call_attempt=%d score=%d tier=%s pickup=%s",
        call_attempt_id,
        result.numeric_score,
        result.tier,
        result.pickup,
    )


def upsert_call_attempt(
    report: VapiEndOfCallReport,
    *,
    session: Session,
) -> CallAttempt | None:
    """Find the lead by phone number, create/update a CallAttempt, save transcript.

    Returns None if no matching lead is found (unknown phone number).
    Idempotent: if a CallAttempt with this vapi_call_id already exists, returns it unchanged.
    """
    phone = report.call.customer.number

    lead: Lead | None = session.query(Lead).filter_by(phone_e164=phone).first()
    if lead is None:
        logger.warning("No lead found for phone %s (vapi_call_id=%s)", phone, report.call.id)
        return None

    # Idempotency: skip if we've already processed this call
    existing: CallAttempt | None = (
        session.query(CallAttempt).filter_by(vapi_call_id=report.call.id).first()
    )
    if existing is not None:
        logger.debug("Duplicate end-of-call-report for vapi_call_id=%s — skipping", report.call.id)
        return existing

    attempt_number = session.query(CallAttempt).filter_by(lead_id=lead.id).count() + 1

    started_at = report.call.started_at
    ended_at = report.call.ended_at
    duration: int | None = None
    if started_at and ended_at:
        duration = int((ended_at - started_at).total_seconds())

    attempt = CallAttempt(
        lead_id=lead.id,
        attempt_number=attempt_number,
        status=CallStatus.COMPLETED,
        vapi_call_id=report.call.id,
        ended_reason=report.ended_reason,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration,
    )
    session.add(attempt)
    session.flush()

    raw_messages = [m.model_dump() for m in report.messages]
    transcript = Transcript(
        call_attempt_id=attempt.id,
        raw_jsonb={"messages": raw_messages, "ended_reason": report.ended_reason},
        plaintext=report.transcript or "",
    )
    session.add(transcript)
    session.commit()

    return attempt


def _build_end_of_call_report(report: VapiEndOfCallReport) -> EndOfCallReport:
    """Convert a Vapi webhook report to the voice layer's EndOfCallReport."""
    started_at = report.call.started_at
    ended_at = report.call.ended_at
    duration = 0
    if started_at and ended_at:
        duration = int((ended_at - started_at).total_seconds())

    messages = tuple(
        TranscriptMessage(role=m.role, message=m.message, time=m.time, duration=m.duration)
        for m in report.messages
    )
    return EndOfCallReport(
        call_id=report.call.id,
        ended_reason=report.ended_reason,
        transcript_text=report.transcript or "",
        messages=messages,
        duration_seconds=max(0, duration),
    )
