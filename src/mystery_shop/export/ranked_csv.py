"""Export scored leads to a ranked CSV for SDR consumption.

Sort order: HOT → WARM → COLD, then numeric_score ASC (worst experience first
within a tier), then google_reviews_count DESC (larger restaurants first).
One row per lead; only leads with at least one completed score are included.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from mystery_shop.db.models import CallAttempt, Extraction, Lead, Score

_TIER_ORDER = {"HOT": 0, "WARM": 1, "COLD": 2}

_COLUMNS = [
    "rank",
    "restaurant_name",
    "phone_e164",
    "city",
    "state",
    "tier",
    "numeric_score",
    "pickup",
    "summary_one_liner",
    "website",
    "google_reviews_count",
    "call_attempt_id",
]


def write_ranked_csv(session: Session, output_path: Path) -> int:
    """Query all scored leads, sort by SDR priority, write to *output_path*.

    Returns the number of rows written.
    """
    rows = (
        session.query(Lead, Score, CallAttempt)
        .join(CallAttempt, CallAttempt.lead_id == Lead.id)
        .join(Extraction, Extraction.call_attempt_id == CallAttempt.id)
        .join(Score, Score.extraction_id == Extraction.id)
        .all()
    )

    # If a lead has multiple attempts / scores, keep the one with the highest Score.id
    best: dict[int, tuple[Lead, Score, CallAttempt]] = {}
    for lead, score, attempt in rows:
        if lead.id not in best or score.id > best[lead.id][1].id:
            best[lead.id] = (lead, score, attempt)

    sorted_rows = sorted(
        best.values(),
        key=lambda t: (
            _TIER_ORDER.get(str(t[1].tier), 9),
            t[1].numeric_score,
            -(t[0].google_reviews_count or 0),
        ),
    )

    records: list[dict[str, Any]] = [
        {
            "rank": i + 1,
            "restaurant_name": lead.restaurant_name,
            "phone_e164": lead.phone_e164,
            "city": lead.city or "",
            "state": lead.state or "",
            "tier": str(score.tier),
            "numeric_score": score.numeric_score,
            "pickup": score.pickup,
            "summary_one_liner": score.summary_one_liner or "",
            "website": lead.website or "",
            "google_reviews_count": lead.google_reviews_count,
            "call_attempt_id": attempt.id,
        }
        for i, (lead, score, attempt) in enumerate(sorted_rows)
    ]

    df = pd.DataFrame(records, columns=_COLUMNS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return len(df)
