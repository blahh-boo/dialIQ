#!/usr/bin/env python
"""Test if Haiku can handle CallFacts extraction vs Sonnet."""

from pathlib import Path
from mystery_shop.config import get_settings
from mystery_shop.llm.claude_client import ClaudeClient
from mystery_shop.llm.classifier import classify_answered_by
from mystery_shop.llm.extractor import extract_call_facts, EXTRACTOR_MODEL
from mystery_shop.voice.base import EndOfCallReport, TranscriptMessage
import json

settings = get_settings()
client = ClaudeClient(settings.anthropic_api_key.get_secret_value())

transcripts_dir = Path("samples/transcripts")
for transcript_file in sorted(transcripts_dir.glob("*.json")):
    data = json.loads(transcript_file.read_text())

    # Build EndOfCallReport
    messages = tuple(
        TranscriptMessage(role=m["role"], message=m["message"], time=m["time"], duration=m["duration"])
        for m in data["messages"]
    )
    report = EndOfCallReport(
        call_id=data["call_id"],
        ended_reason=data["ended_reason"],
        transcript_text=data["transcript_text"],
        messages=messages,
        duration_seconds=data["duration_seconds"],
    )

    # Classify first
    answered_by = classify_answered_by(report.transcript_text, client=client)

    # Extract with current model (Sonnet)
    facts = extract_call_facts(report, answered_by=answered_by, client=client)

    print(f"\n{transcript_file.name} ({answered_by})")
    print(f"  pickup={facts.pickup}")
    print(f"  rings_to_answer={facts.rings_to_answer}")
    print(f"  put_on_hold={facts.put_on_hold}")
    print(f"  transfer_count={facts.transfer_count}")
    print(f"  ces={facts.customer_effort_score}")
    if facts.key_failure_quote:
        print(f"  quote: {facts.key_failure_quote[:60]}")
