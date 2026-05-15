"""Interleave logic — prevents calling the same restaurant twice in a row.

Rationale: back-to-back calls to the same number look spammy and waste a retry slot.
The worker tracks the last-called lead_id and skips it if it surfaces again at the
head of the queue.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mystery_shop.db.models import Lead


def next_lead(
    candidates: list[Lead],
    *,
    last_called_id: int | None,
) -> Lead | None:
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
