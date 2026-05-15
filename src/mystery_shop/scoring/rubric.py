"""Deterministic scoring rubric.

`score_call(facts)` is a pure function: same `CallFacts` → same `ScoreResult`.
Score starts at 100 and deductions are subtracted, floored at 0.
Bump RUBRIC_VERSION whenever weights or logic change; each version is stored
alongside the score row for full auditability.
"""

from __future__ import annotations

from mystery_shop.llm.schemas import CallFacts, Deduction, ScoreResult
from mystery_shop.scoring.tiers import classify_tier

RUBRIC_VERSION = "v1"


def score_call(facts: CallFacts) -> ScoreResult:
    """Score a single call. Returns a fully-populated `ScoreResult`."""
    if not facts.pickup:
        return ScoreResult(
            pickup=False,
            numeric_score=0,
            tier="HOT",
            deductions=(Deduction(reason="Call not picked up", points=100),),
            rubric_version=RUBRIC_VERSION,
        )

    deductions: list[Deduction] = []

    # ── rings to answer ──────────────────────────────────────────────────────
    rings = facts.rings_to_answer
    if rings is None:
        deductions.append(Deduction(reason="Ring count unknown", points=3))
    elif rings >= 5:
        deductions.append(Deduction(reason=f"Very slow to answer ({rings} rings)", points=10))
    elif rings >= 3:
        deductions.append(Deduction(reason=f"Slow to answer ({rings} rings)", points=5))

    # ── hold ─────────────────────────────────────────────────────────────────
    if facts.put_on_hold:
        deductions.append(Deduction(reason="Put on hold", points=5))
        hold = facts.hold_time_seconds
        if hold is not None:
            if hold > 120:
                deductions.append(Deduction(reason=f"Extended hold ({hold}s)", points=20))
            elif hold > 60:
                deductions.append(Deduction(reason=f"Long hold ({hold}s)", points=12))
            elif hold > 30:
                deductions.append(Deduction(reason=f"Moderate hold ({hold}s)", points=5))

    # ── transfers ────────────────────────────────────────────────────────────
    transfers = facts.transfer_count
    if transfers == 1:
        deductions.append(Deduction(reason="1 transfer", points=12))
    elif transfers == 2:
        deductions.append(Deduction(reason="2 transfers", points=20))
    elif transfers >= 3:
        deductions.append(Deduction(reason=f"{transfers} transfers", points=30))

    # ── restaurant abandoned the call ────────────────────────────────────────
    if facts.call_abandoned_by_restaurant:
        deductions.append(Deduction(reason="Restaurant abandoned the call", points=30))

    # ── interruptions ────────────────────────────────────────────────────────
    interruptions = facts.interruption_count
    if interruptions >= 5:
        deductions.append(Deduction(reason=f"Frequent interruptions ({interruptions}x)", points=20))
    elif interruptions >= 3:
        deductions.append(Deduction(reason=f"Multiple interruptions ({interruptions}x)", points=15))
    elif interruptions >= 1:
        deductions.append(Deduction(reason=f"Interrupted {interruptions}x", points=8))

    # ── had to repeat information ────────────────────────────────────────────
    repeats = facts.repeated_information_count
    if repeats >= 3:
        deductions.append(Deduction(reason=f"Had to repeat information {repeats}x", points=25))
    elif repeats == 2:
        deductions.append(Deduction(reason="Had to repeat information twice", points=18))
    elif repeats == 1:
        deductions.append(Deduction(reason="Had to repeat information once", points=10))

    # ── upsell ───────────────────────────────────────────────────────────────
    if not facts.upsell_attempted:
        deductions.append(Deduction(reason="No upsell attempted", points=5))

    # ── customer effort score (1=effortless … 5=very high effort) ────────────
    ces = facts.customer_effort_score
    if ces == 5:
        deductions.append(Deduction(reason="Very high caller effort (5/5)", points=22))
    elif ces == 4:
        deductions.append(Deduction(reason="High caller effort (4/5)", points=15))
    elif ces == 3:
        deductions.append(Deduction(reason="Moderate caller effort (3/5)", points=8))
    # 1-2: no deduction

    total_deducted = sum(d.points for d in deductions)
    numeric_score = max(0, 100 - total_deducted)
    tier = classify_tier(
        pickup=True,
        call_abandoned_by_restaurant=facts.call_abandoned_by_restaurant,
        numeric_score=numeric_score,
    )

    return ScoreResult(
        pickup=True,
        numeric_score=numeric_score,
        tier=tier,
        deductions=tuple(deductions),
        rubric_version=RUBRIC_VERSION,
    )
