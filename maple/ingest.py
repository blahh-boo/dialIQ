"""Lead ingest: read the xlsx, normalize each row (phone E.164, zip, timezone,
state, name-from-URL), and upsert into the `leads` table.

`normalize_row` is the pure transform; `load_xlsx` is the DB-facing loader.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import pandas as pd
import pgeocode
import phonenumbers
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from timezonefinder import TimezoneFinder

from maple.db import Lead, upsert_insert

logger = logging.getLogger(__name__)

_tf = TimezoneFinder()
_geo_us = pgeocode.Nominatim("US")

# Full US state names (lowercase) → IANA timezone.
# Approximation for states spanning multiple zones; scheduler only needs
# a ±1h accuracy to stay inside the 11am-2pm call window.
_STATE_TZ: dict[str, str] = {
    "alabama": "America/Chicago",
    "alaska": "America/Anchorage",
    "arizona": "America/Phoenix",
    "arkansas": "America/Chicago",
    "california": "America/Los_Angeles",
    "colorado": "America/Denver",
    "connecticut": "America/New_York",
    "delaware": "America/New_York",
    "florida": "America/New_York",
    "georgia": "America/New_York",
    "hawaii": "Pacific/Honolulu",
    "idaho": "America/Denver",
    "illinois": "America/Chicago",
    "indiana": "America/Indiana/Indianapolis",
    "iowa": "America/Chicago",
    "kansas": "America/Chicago",
    "kentucky": "America/New_York",
    "louisiana": "America/Chicago",
    "maine": "America/New_York",
    "maryland": "America/New_York",
    "massachusetts": "America/New_York",
    "michigan": "America/Detroit",
    "minnesota": "America/Chicago",
    "mississippi": "America/Chicago",
    "missouri": "America/Chicago",
    "montana": "America/Denver",
    "nebraska": "America/Chicago",
    "nevada": "America/Los_Angeles",
    "new hampshire": "America/New_York",
    "new jersey": "America/New_York",
    "new mexico": "America/Denver",
    "new york": "America/New_York",
    "north carolina": "America/New_York",
    "north dakota": "America/Chicago",
    "ohio": "America/New_York",
    "oklahoma": "America/Chicago",
    "oregon": "America/Los_Angeles",
    "pennsylvania": "America/New_York",
    "rhode island": "America/New_York",
    "south carolina": "America/New_York",
    "south dakota": "America/Chicago",
    "tennessee": "America/Chicago",
    "texas": "America/Chicago",
    "utah": "America/Denver",
    "vermont": "America/New_York",
    "virginia": "America/New_York",
    "washington": "America/Los_Angeles",
    "west virginia": "America/New_York",
    "wisconsin": "America/Chicago",
    "wyoming": "America/Denver",
    "district of columbia": "America/New_York",
    "dc": "America/New_York",
}

# Full US state name (lowercase) → 2-letter USPS code. The `leads.state` column
# is varchar(2); source files vary between "Virginia" and "VA", so normalize.
_STATE_ABBR: dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
}


def _normalize_state(raw: str | None) -> str | None:
    """Return a 2-letter USPS state code, or None if it can't be resolved.

    Handles both source formats: already-abbreviated ("VA") passes through
    uppercased; a full name ("Virginia") is mapped. Anything unrecognized
    returns None rather than overflowing the varchar(2) column.
    """
    if not raw:
        return None
    s = raw.strip()
    if len(s) == 2 and s.isalpha():
        return s.upper()
    return _STATE_ABBR.get(s.lower())


class PhoneParseError(ValueError):
    """Raised when a phone number cannot be normalized to E.164."""


class LeadIngest(BaseModel):
    """A normalized lead row ready for DB insertion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    restaurant_name: str
    phone_e164: str
    website: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    timezone: str | None = None
    google_reviews_count: int | None = None
    source_row_index: int
    raw_metadata: dict[str, Any]


def _parse_phone(raw: Any) -> str:
    """Convert a raw xlsx phone value to an E.164 string.

    The xlsx stores phones as float64 (e.g. 14345849382.0). Strips formatting,
    prepends '+' for digit-only strings, and validates via the phonenumbers lib.
    """
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        raise PhoneParseError("missing phone number")

    if isinstance(raw, float):
        # xlsx stores phones as float64 with US country code included (e.g. 14345849382.0)
        candidate = "+" + str(int(raw))
    else:
        # strip formatting chars; keep any leading '+' if present
        candidate = re.sub(r"[^\d+]", "", str(raw).strip())

    try:
        # passing "US" as default region handles bare 10-digit numbers correctly;
        # '+'-prefixed strings are parsed as international regardless of region
        parsed = phonenumbers.parse(candidate, "US")
    except phonenumbers.NumberParseException as exc:
        raise PhoneParseError(f"cannot parse {raw!r}: {exc}") from exc

    if not phonenumbers.is_valid_number(parsed):
        raise PhoneParseError(f"invalid number: {raw!r}")

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def _normalize_postal_code(raw: Any) -> str | None:
    """Coerce a float/int/str postal code to a zero-padded 5-digit string."""
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None
    if isinstance(raw, float):
        return str(int(raw)).zfill(5)
    return str(raw).strip().zfill(5)


def _name_from_url(url: str) -> str:
    """Derive a human-readable restaurant name from its website URL.

    Best-effort: strips scheme, www., TLD, and separators, then title-cases.
    The pre-call LLM step refines this if needed.
    """
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    domain = re.sub(r"(?i)^www\.", "", domain)
    domain = re.sub(r"\.[^.]+$", "", domain)  # strip TLD
    name = re.sub(r"[-_.]", " ", domain).strip()
    return name.title() if name else "Unknown Restaurant"


def _infer_timezone(postal_code: str | None, state: str | None) -> str | None:
    """Infer IANA timezone from postal code (precise) or state (approximate).

    Returns None only when both lookups fail.
    """
    if postal_code:
        try:
            result = _geo_us.query_postal_code(postal_code)
            if result is not None and not math.isnan(float(result.latitude)):
                tz = _tf.timezone_at(lng=float(result.longitude), lat=float(result.latitude))
                if tz:
                    return tz
        except Exception as exc:
            logger.debug("pgeocode/timezonefinder lookup failed for %r: %s", postal_code, exc)

    if state:
        return _STATE_TZ.get(state.strip().lower())

    return None


def normalize_row(row: dict[str, Any], *, source_row_index: int) -> LeadIngest:
    """Normalize a single raw xlsx row into a `LeadIngest`.

    Raises `PhoneParseError` for rows that cannot be dialled (missing/invalid phone).
    All other missing fields are tolerated and stored as None.
    """
    phone_e164 = _parse_phone(row.get("Location Phone"))

    website = (
        str(row["organization_website_url"]).strip()
        if row.get("organization_website_url")
        else None
    )
    restaurant_name = _name_from_url(website) if website else "Unknown Restaurant"

    postal_code = _normalize_postal_code(row.get("organization_postal_code"))
    raw_state = str(row["organization_state"]).strip() if row.get("organization_state") else None
    timezone = _infer_timezone(postal_code, raw_state)  # _STATE_TZ is keyed by full name
    state = _normalize_state(raw_state)  # store the 2-letter code (varchar(2))

    raw_reviews = row.get("Google Reviews Count")
    google_reviews_count: int | None = (
        int(raw_reviews)
        if raw_reviews is not None
        and not (isinstance(raw_reviews, float) and math.isnan(raw_reviews))
        else None
    )

    raw_metadata: dict[str, Any] = {
        k: (None if (isinstance(v, float) and math.isnan(v)) else v)
        for k, v in {
            "contact_first_name": row.get("first_name"),
            "contact_last_name": row.get("last_name"),
            "contact_email": row.get("email"),
            "organization_raw_address": row.get("organization_raw_address"),
            "google_maps_url": row.get("Google Maps Url"),
        }.items()
    }

    return LeadIngest(
        restaurant_name=restaurant_name,
        phone_e164=phone_e164,
        website=website,
        address=str(row["organization_street_address"]).strip()
        if row.get("organization_street_address")
        else None,
        city=str(row["organization_city"]).strip() if row.get("organization_city") else None,
        state=state,
        postal_code=postal_code,
        timezone=timezone,
        google_reviews_count=google_reviews_count,
        source_row_index=source_row_index,
        raw_metadata=raw_metadata,
    )


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
            upsert_insert()(Lead)
            .values(**_lead_values(lead))
            .on_conflict_do_nothing(index_elements=["phone_e164"])
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
