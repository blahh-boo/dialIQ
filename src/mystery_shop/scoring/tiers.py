"""Tier classification: HOT / WARM / COLD.

HOT  — pickup failed, restaurant abandoned the call, or score ≤ 40.
         These are Maple's highest-priority leads.
WARM — score 41-70.  Some friction; worth an SDR call.
COLD — score ≥ 71.  Phone experience adequate; lower priority.
"""

from __future__ import annotations

from mystery_shop.llm.schemas import TierLiteral

HOT_MAX = 40
COLD_MIN = 71


def classify_tier(
    *,
    pickup: bool,
    call_abandoned_by_restaurant: bool,
    numeric_score: int,
) -> TierLiteral:
    """Return the HOT/WARM/COLD tier for a scored call.

    Categorical overrides (pickup failure, abandonment) always resolve to HOT
    regardless of the numeric score.
    """
    if not pickup or call_abandoned_by_restaurant:
        return "HOT"
    if numeric_score <= HOT_MAX:
        return "HOT"
    if numeric_score >= COLD_MIN:
        return "COLD"
    return "WARM"
