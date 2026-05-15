"""Haiku SDR one-liner generator.

Produces a single punchy sentence that arms an SDR for outreach.
Called after scoring; result stored in scores.summary_one_liner.
"""

from __future__ import annotations

from mystery_shop.llm.claude_client import ClaudeClient
from mystery_shop.llm.schemas import CallFacts, ScoreResult

SUMMARIZER_MODEL = "claude-haiku-4-5"
SUMMARIZER_PROMPT_VERSION = "summarizer_v1.txt"


def generate_one_liner(
    facts: CallFacts,
    result: ScoreResult,
    *,
    client: ClaudeClient,
) -> str:
    """Return a ≤25-word SDR one-liner for this call result."""
    system = client.load_prompt(SUMMARIZER_PROMPT_VERSION)

    deduction_lines = "\n".join(f"- {d.reason} (-{d.points})" for d in result.deductions)
    user_content = (
        f"tier: {result.tier}\n"
        f"score: {result.numeric_score}/100\n"
        f"pickup: {facts.pickup}\n"
        f"answered_by: (see facts)\n"
        f"put_on_hold: {facts.put_on_hold}\n"
        f"hold_time_seconds: {facts.hold_time_seconds}\n"
        f"transfer_count: {facts.transfer_count}\n"
        f"call_abandoned_by_restaurant: {facts.call_abandoned_by_restaurant}\n"
        f"interruption_count: {facts.interruption_count}\n"
        f"repeated_information_count: {facts.repeated_information_count}\n"
        f"customer_effort_score: {facts.customer_effort_score}/5\n"
        f"key_failure_quote: {facts.key_failure_quote!r}\n"
        f"\ndeductions:\n{deduction_lines or '(none)'}"
    )

    response = client.complete(
        model=SUMMARIZER_MODEL,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        max_tokens=80,
        temperature=0.0,
    )

    for block in response.content:
        if block.type == "text":
            return block.text.strip()

    return f"{result.tier}: Score {result.numeric_score}/100."
