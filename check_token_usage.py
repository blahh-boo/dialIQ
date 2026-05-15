#!/usr/bin/env python
"""Debug script: check actual token usage for each extraction."""

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

    # Classify
    answered_by = classify_answered_by(report.transcript_text, client=client)

    # Extract and check token usage
    # Note: to see token usage, you'd need to modify extractor.py temporarily to print response.usage
    facts = extract_call_facts(report, answered_by=answered_by, client=client)

    print(f"\n{transcript_file.name}")
    print(f"  answered_by: {answered_by}")
    print(f"  pickup: {facts.pickup}")
    print(f"  extraction fields populated: {sum(1 for f in [facts.rings_to_answer, facts.put_on_hold, facts.transfer_count, facts.interruption_count, facts.repeated_information_count, facts.customer_effort_score] if f is not None or f is False)}")
