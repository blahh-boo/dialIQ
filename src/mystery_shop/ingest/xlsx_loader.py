"""Load restaurant leads from an xlsx file into the leads table."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from mystery_shop.db.models import Lead
from mystery_shop.ingest.normalize import LeadIngest, PhoneParseError, normalize_row

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = {"Location Phone"}
_DROP_COLUMNS = {"Unnamed: 3"}


@dataclass(frozen=True)
class IngestResult:
    inserted: int
    skipped_no_phone: int
    skipped_duplicate: int
    error_count: int

    @property
    def total_processed(self) -> int:
        return self.inserted + self.skipped_no_phone + self.skipped_duplicate + self.error_count


def load_xlsx(path: Path, session: Session) -> IngestResult:
    """Read leads from *path*, normalize, and upsert into `leads`.

    Duplicate phones (same phone already in DB, or repeated in the file) are
    silently skipped — `phone_e164` has a unique constraint.
    Rows missing a parseable phone are logged and counted separately.
    """
    df = _read_and_clean(path)

    inserted = skipped_no_phone = skipped_duplicate = error_count = 0

    rows = cast(list[dict[str, Any]], df.to_dict("records"))
    for idx, row in enumerate(rows):
        try:
            lead = normalize_row(row, source_row_index=idx)
        except PhoneParseError as exc:
            logger.debug("Row %d skipped — %s", idx, exc)
            skipped_no_phone += 1
            continue
        except Exception as exc:
            logger.warning("Row %d error — %s", idx, exc)
            error_count += 1
            continue

        result = session.execute(
            pg_insert(Lead)
            .values(**_lead_values(lead))
            .on_conflict_do_nothing(constraint="uq_leads_phone_e164")
            .returning(Lead.id)
        )
        if result.scalar_one_or_none() is not None:
            inserted += 1
        else:
            skipped_duplicate += 1

    logger.info(
        "Ingest complete — inserted=%d duplicates=%d no_phone=%d errors=%d",
        inserted,
        skipped_duplicate,
        skipped_no_phone,
        error_count,
    )
    return IngestResult(
        inserted=inserted,
        skipped_no_phone=skipped_no_phone,
        skipped_duplicate=skipped_duplicate,
        error_count=error_count,
    )


def _read_and_clean(path: Path) -> pd.DataFrame:
    df: pd.DataFrame = pd.read_excel(path)

    missing = _REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"xlsx is missing required columns: {missing}")

    return df.drop(columns=[c for c in _DROP_COLUMNS if c in df.columns])


def _lead_values(lead: LeadIngest) -> dict[str, Any]:
    return {
        "restaurant_name": lead.restaurant_name,
        "phone_e164": lead.phone_e164,
        "website": lead.website,
        "address": lead.address,
        "city": lead.city,
        "state": lead.state,
        "postal_code": lead.postal_code,
        "timezone": lead.timezone,
        "google_reviews_count": lead.google_reviews_count,
        "source_row_index": lead.source_row_index,
        "raw_metadata": lead.raw_metadata,
    }
