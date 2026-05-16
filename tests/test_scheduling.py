"""Tests for scheduling logic — no DB, no network required."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from maple.scheduling import (
    CALL_CLOSE_HOUR,
    CALL_OPEN_HOUR,
    is_callable_at,
    next_lead,
)

# ── is_callable_at ────────────────────────────────────────────────────────────


def _utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2024, 6, 15, hour, minute, tzinfo=UTC)


def test_callable_at_open_hour() -> None:
    # 11:00 AM Eastern = 15:00 UTC (summer)
    assert is_callable_at("America/New_York", _utc(15, 0)) is True


def test_callable_at_one_minute_before_close() -> None:
    # 1:59 PM Eastern = 17:59 UTC
    assert is_callable_at("America/New_York", _utc(17, 59)) is True


def test_not_callable_at_close_hour() -> None:
    # 2:00 PM Eastern = 18:00 UTC — window closed
    assert is_callable_at("America/New_York", _utc(18, 0)) is False


def test_not_callable_before_open() -> None:
    # 10:59 AM Eastern = 14:59 UTC
    assert is_callable_at("America/New_York", _utc(14, 59)) is False


def test_callable_in_pacific_timezone() -> None:
    # 11:30 AM Pacific (PDT, UTC-7) = 18:30 UTC
    assert is_callable_at("America/Los_Angeles", _utc(18, 30)) is True


def test_not_callable_in_pacific_before_open() -> None:
    # 10:00 AM Pacific (PDT, UTC-7) = 17:00 UTC
    assert is_callable_at("America/Los_Angeles", _utc(17, 0)) is False


def test_callable_in_chicago_timezone() -> None:
    # 12:00 PM Central (CDT, UTC-5) = 17:00 UTC
    assert is_callable_at("America/Chicago", _utc(17, 0)) is True


def test_none_timezone_not_callable() -> None:
    assert is_callable_at(None, _utc(15, 0)) is False


def test_invalid_timezone_not_callable() -> None:
    assert is_callable_at("Mars/OlympusMons", _utc(15, 0)) is False


def test_call_window_constants_sensible() -> None:
    assert CALL_OPEN_HOUR == 11
    assert CALL_CLOSE_HOUR == 14
    assert CALL_OPEN_HOUR < CALL_CLOSE_HOUR


@pytest.mark.parametrize("hour", range(CALL_OPEN_HOUR, CALL_CLOSE_HOUR))
def test_all_hours_in_window_callable(hour: int) -> None:
    # Eastern summer: UTC offset is -4, so +4 to get UTC
    assert is_callable_at("America/New_York", _utc(hour + 4)) is True


@pytest.mark.parametrize("utc_hour", [4, 12, 14, 18, 19])
def test_hours_outside_window_not_callable(utc_hour: int) -> None:
    # 4=midnight ET, 12=8am ET, 14=10am ET, 18=2pm ET, 19=3pm ET
    assert is_callable_at("America/New_York", _utc(utc_hour)) is False


# ── next_lead interleave ──────────────────────────────────────────────────────


class _FakeLead:
    """Minimal stand-in for Lead ORM model in interleave tests."""

    def __init__(self, lead_id: int) -> None:
        self.id = lead_id


def test_next_lead_returns_first_when_no_last() -> None:
    leads = [_FakeLead(1), _FakeLead(2), _FakeLead(3)]
    result = next_lead(leads, last_called_id=None)  # type: ignore[arg-type]
    assert result is not None
    assert result.id == 1


def test_next_lead_skips_last_called() -> None:
    leads = [_FakeLead(1), _FakeLead(2), _FakeLead(3)]
    result = next_lead(leads, last_called_id=1)  # type: ignore[arg-type]
    assert result is not None
    assert result.id == 2


def test_next_lead_skips_non_head_last_called() -> None:
    leads = [_FakeLead(2), _FakeLead(1), _FakeLead(3)]
    result = next_lead(leads, last_called_id=2)  # type: ignore[arg-type]
    assert result is not None
    assert result.id == 1


def test_next_lead_empty_returns_none() -> None:
    assert next_lead([], last_called_id=None) is None  # type: ignore[arg-type]


def test_next_lead_only_one_lead_returns_it_anyway() -> None:
    leads = [_FakeLead(5)]
    result = next_lead(leads, last_called_id=5)  # type: ignore[arg-type]
    assert result is not None
    assert result.id == 5


def test_next_lead_all_same_returns_first() -> None:
    leads = [_FakeLead(7), _FakeLead(7)]
    result = next_lead(leads, last_called_id=7)  # type: ignore[arg-type]
    assert result is not None
    assert result.id == 7
