"""Unit tests for the deterministic scoring rubric.

All tests are pure Python — no network, no DB, no Claude calls.
Each test targets a specific deduction rule or tier boundary so failures
point directly at the broken weight.
"""

from __future__ import annotations

import pytest

from mystery_shop.scoring.rubric import RUBRIC_VERSION, score_call
from mystery_shop.scoring.tiers import COLD_MIN, HOT_MAX, classify_tier
from tests.factories import make_call_facts

# ── tier classification ───────────────────────────────────────────────────────


def test_no_pickup_is_always_hot() -> None:
    result = score_call(make_call_facts(pickup=False))
    assert result.tier == "HOT"
    assert result.pickup is False
    assert result.numeric_score == 0


def test_abandoned_is_always_hot_regardless_of_score() -> None:
    # Even a near-perfect call that ends in abandonment must be HOT.
    result = score_call(make_call_facts(call_abandoned_by_restaurant=True))
    assert result.tier == "HOT"


def test_classify_tier_boundaries() -> None:
    assert (
        classify_tier(pickup=True, call_abandoned_by_restaurant=False, numeric_score=HOT_MAX)
        == "HOT"
    )
    assert (
        classify_tier(pickup=True, call_abandoned_by_restaurant=False, numeric_score=HOT_MAX + 1)
        == "WARM"
    )
    assert (
        classify_tier(pickup=True, call_abandoned_by_restaurant=False, numeric_score=COLD_MIN - 1)
        == "WARM"
    )
    assert (
        classify_tier(pickup=True, call_abandoned_by_restaurant=False, numeric_score=COLD_MIN)
        == "COLD"
    )


def test_perfect_call_scores_100_cold() -> None:
    # Defaults in make_call_facts represent a flawless call.
    result = score_call(make_call_facts())
    assert result.numeric_score == 100
    assert result.tier == "COLD"
    assert result.deductions == ()


def test_score_never_goes_below_zero() -> None:
    result = score_call(
        make_call_facts(
            rings_to_answer=10,
            put_on_hold=True,
            hold_time_seconds=300,
            transfer_count=5,
            call_abandoned_by_restaurant=True,
            interruption_count=10,
            repeated_information_count=5,
            upsell_attempted=False,
        )
    )
    assert result.numeric_score == 0


def test_rubric_version_is_set() -> None:
    result = score_call(make_call_facts())
    assert result.rubric_version == RUBRIC_VERSION


# ── rings_to_answer ───────────────────────────────────────────────────────────


def test_rings_none_deducts_3() -> None:
    result = score_call(make_call_facts(rings_to_answer=None))
    assert result.numeric_score == 97


def test_rings_2_no_deduction() -> None:
    result = score_call(make_call_facts(rings_to_answer=2))
    assert result.numeric_score == 100


def test_rings_3_deducts_5() -> None:
    result = score_call(make_call_facts(rings_to_answer=3))
    assert result.numeric_score == 95


def test_rings_5_deducts_10() -> None:
    result = score_call(make_call_facts(rings_to_answer=5))
    assert result.numeric_score == 90


# ── put_on_hold + hold_time ───────────────────────────────────────────────────


def test_on_hold_base_deducts_5() -> None:
    result = score_call(make_call_facts(put_on_hold=True, hold_time_seconds=15))
    assert result.numeric_score == 95


def test_hold_31s_deducts_10() -> None:
    result = score_call(make_call_facts(put_on_hold=True, hold_time_seconds=31))
    assert result.numeric_score == 90  # -5 base -5 moderate


def test_hold_61s_deducts_17() -> None:
    result = score_call(make_call_facts(put_on_hold=True, hold_time_seconds=61))
    assert result.numeric_score == 83  # -5 base -12 long


def test_hold_121s_deducts_25() -> None:
    result = score_call(make_call_facts(put_on_hold=True, hold_time_seconds=121))
    assert result.numeric_score == 75  # -5 base -20 extended


# ── transfer_count ────────────────────────────────────────────────────────────


def test_1_transfer_deducts_12() -> None:
    result = score_call(make_call_facts(transfer_count=1))
    assert result.numeric_score == 88


def test_2_transfers_deducts_20() -> None:
    result = score_call(make_call_facts(transfer_count=2))
    assert result.numeric_score == 80


def test_3_transfers_deducts_30() -> None:
    result = score_call(make_call_facts(transfer_count=3))
    assert result.numeric_score == 70
    assert result.tier == "WARM"


# ── interruption_count ────────────────────────────────────────────────────────


def test_1_interruption_deducts_8() -> None:
    result = score_call(make_call_facts(interruption_count=1))
    assert result.numeric_score == 92


def test_3_interruptions_deducts_15() -> None:
    result = score_call(make_call_facts(interruption_count=3))
    assert result.numeric_score == 85


def test_5_interruptions_deducts_20() -> None:
    result = score_call(make_call_facts(interruption_count=5))
    assert result.numeric_score == 80


# ── repeated_information_count ────────────────────────────────────────────────


def test_1_repeat_deducts_10() -> None:
    result = score_call(make_call_facts(repeated_information_count=1))
    assert result.numeric_score == 90


def test_2_repeats_deducts_18() -> None:
    result = score_call(make_call_facts(repeated_information_count=2))
    assert result.numeric_score == 82


def test_3_repeats_deducts_25() -> None:
    result = score_call(make_call_facts(repeated_information_count=3))
    assert result.numeric_score == 75


# ── upsell ────────────────────────────────────────────────────────────────────


def test_no_upsell_deducts_5() -> None:
    result = score_call(make_call_facts(upsell_attempted=False))
    assert result.numeric_score == 95


def test_upsell_no_deduction() -> None:
    result = score_call(make_call_facts(upsell_attempted=True))
    assert result.numeric_score == 100


# ── customer_effort_score ─────────────────────────────────────────────────────


def test_effort_1_no_deduction() -> None:
    result = score_call(make_call_facts(customer_effort_score=1))
    assert result.numeric_score == 100


def test_effort_2_no_deduction() -> None:
    result = score_call(make_call_facts(customer_effort_score=2))
    assert result.numeric_score == 100


def test_effort_3_deducts_8() -> None:
    result = score_call(make_call_facts(customer_effort_score=3))
    assert result.numeric_score == 92


def test_effort_4_deducts_15() -> None:
    result = score_call(make_call_facts(customer_effort_score=4))
    assert result.numeric_score == 85


def test_effort_5_deducts_22() -> None:
    result = score_call(make_call_facts(customer_effort_score=5))
    assert result.numeric_score == 78
    assert result.tier == "COLD"


# ── call_abandoned ────────────────────────────────────────────────────────────


def test_abandoned_deducts_30_and_forces_hot() -> None:
    result = score_call(make_call_facts(call_abandoned_by_restaurant=True))
    assert result.tier == "HOT"
    reasons = {d.reason for d in result.deductions}
    assert any("abandoned" in r.lower() for r in reasons)


# ── compound scenarios ────────────────────────────────────────────────────────


def test_hot_lead_scenario() -> None:
    """Slow pickup, long hold, 2 transfers, repeated twice → clearly HOT."""
    result = score_call(
        make_call_facts(
            rings_to_answer=5,  # -10
            put_on_hold=True,
            hold_time_seconds=90,  # -5 -12
            transfer_count=2,  # -20
            repeated_information_count=2,  # -18
            upsell_attempted=False,  # -5
        )
    )
    assert result.numeric_score == 30
    assert result.tier == "HOT"


def test_warm_lead_scenario() -> None:
    """Minor friction: 3 rings, one brief hold, one repeat."""
    result = score_call(
        make_call_facts(
            rings_to_answer=3,  # -5
            put_on_hold=True,
            hold_time_seconds=20,  # -5
            repeated_information_count=1,  # -10
            upsell_attempted=False,  # -5
        )
    )
    assert result.numeric_score == 75
    assert result.tier == "COLD"


def test_deductions_are_individually_named() -> None:
    """Every deduction has a non-empty reason string."""
    result = score_call(
        make_call_facts(
            rings_to_answer=5,
            put_on_hold=True,
            hold_time_seconds=200,
            transfer_count=3,
            interruption_count=4,
            repeated_information_count=3,
            upsell_attempted=False,
        )
    )
    for deduction in result.deductions:
        assert deduction.reason
        assert deduction.points > 0


@pytest.mark.parametrize(
    ("score", "expected_tier"),
    [
        (100, "COLD"),
        (71, "COLD"),
        (70, "WARM"),
        (41, "WARM"),
        (40, "HOT"),
        (0, "HOT"),
    ],
)
def test_tier_thresholds(score: int, expected_tier: str) -> None:
    tier = classify_tier(pickup=True, call_abandoned_by_restaurant=False, numeric_score=score)
    assert tier == expected_tier
