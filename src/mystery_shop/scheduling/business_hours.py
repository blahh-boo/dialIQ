"""Business-hours gating for outbound calls.

Call window: 11:00 AM - 2:00 PM local time (restaurant's timezone).
Approximation is intentional — leads have state-level timezone resolution and
the scheduler only needs ±1h accuracy to stay inside the window.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime

CALL_OPEN_HOUR = 11  # 11:00 AM local
CALL_CLOSE_HOUR = 14  # 2:00 PM local (exclusive → last eligible start is 1:59 PM)


def is_callable_now(timezone_name: str | None) -> bool:
    """True if the current local time in *timezone_name* is within the call window.

    Returns False for None or unrecognised timezone strings.
    """
    if not timezone_name:
        return False
    try:
        tz = zoneinfo.ZoneInfo(timezone_name)
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        return False
    local = datetime.now(tz)
    return CALL_OPEN_HOUR <= local.hour < CALL_CLOSE_HOUR


def is_callable_at(timezone_name: str | None, when: datetime) -> bool:
    """True if *when* (tz-aware) falls inside the call window for *timezone_name*.

    Used in tests where you want to check a specific moment rather than now.
    """
    if not timezone_name:
        return False
    try:
        tz = zoneinfo.ZoneInfo(timezone_name)
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        return False
    local = when.astimezone(tz)
    return CALL_OPEN_HOUR <= local.hour < CALL_CLOSE_HOUR
