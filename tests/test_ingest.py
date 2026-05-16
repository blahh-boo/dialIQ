"""Unit tests for ingest normalization (no DB, no network required)."""

from __future__ import annotations

import pytest

from mystery_shop.ingest.normalize import (
    PhoneParseError,
    _infer_timezone,
    _name_from_url,
    _normalize_postal_code,
    _parse_phone,
    normalize_row,
)

# ── phone parsing ─────────────────────────────────────────────────────────────


def test_parse_phone_from_float() -> None:
    assert _parse_phone(14345849382.0) == "+14345849382"


def test_parse_phone_from_int_string() -> None:
    assert _parse_phone("14345849382") == "+14345849382"


def test_parse_phone_from_formatted_string() -> None:
    assert _parse_phone("(434) 584-9382") == "+14345849382"


def test_parse_phone_10_digit_no_country_code() -> None:
    assert _parse_phone("4345849382") == "+14345849382"


def test_parse_phone_none_raises() -> None:
    with pytest.raises(PhoneParseError, match="missing"):
        _parse_phone(None)


def test_parse_phone_nan_raises() -> None:
    with pytest.raises(PhoneParseError, match="missing"):
        _parse_phone(float("nan"))


def test_parse_phone_invalid_raises() -> None:
    with pytest.raises(PhoneParseError):
        _parse_phone("1234")


def test_parse_phone_empty_string_raises() -> None:
    with pytest.raises(PhoneParseError):
        _parse_phone("")


# ── postal code normalization ─────────────────────────────────────────────────


def test_normalize_postal_float() -> None:
    assert _normalize_postal_code(23970.0) == "23970"


def test_normalize_postal_zero_pad() -> None:
    # Connecticut zips start with 0 — must not lose the leading zero
    assert _normalize_postal_code(6010.0) == "06010"


def test_normalize_postal_nan_returns_none() -> None:
    assert _normalize_postal_code(float("nan")) is None


def test_normalize_postal_none_returns_none() -> None:
    assert _normalize_postal_code(None) is None


def test_normalize_postal_string() -> None:
    assert _normalize_postal_code("10012") == "10012"


# ── name from URL ─────────────────────────────────────────────────────────────


def test_name_from_url_strips_www_and_tld() -> None:
    assert _name_from_url("http://www.boloco.com") == "Boloco"


def test_name_from_url_hyphenated() -> None:
    assert _name_from_url("https://www.the-great-burger.com") == "The Great Burger"


def test_name_from_url_no_www() -> None:
    assert _name_from_url("http://pinkberry.com") == "Pinkberry"


def test_name_from_url_empty_fallback() -> None:
    assert _name_from_url("") == "Unknown Restaurant"


# ── timezone inference ────────────────────────────────────────────────────────


def test_infer_timezone_from_state_full_name() -> None:
    assert _infer_timezone(None, "Virginia") == "America/New_York"


def test_infer_timezone_california() -> None:
    assert _infer_timezone(None, "California") == "America/Los_Angeles"


def test_infer_timezone_case_insensitive() -> None:
    assert _infer_timezone(None, "FLORIDA") == "America/New_York"


def test_infer_timezone_both_none() -> None:
    assert _infer_timezone(None, None) is None


def test_infer_timezone_unknown_state() -> None:
    assert _infer_timezone(None, "United States") is None


# ── normalize_row ─────────────────────────────────────────────────────────────


def _sample_row() -> dict[str, object]:
    return {
        "first_name": "Kyle",
        "last_name": "Svilar",
        "organization_website_url": "http://www.313franklin.com",
        "email": "kyle@example.com",
        "organization_street_address": None,
        "organization_raw_address": "South Hill, Virginia 23970, US",
        "organization_state": "Virginia",
        "organization_city": "South Hill",
        "organization_country": "United States",
        "organization_postal_code": 23970.0,
        "Google Reviews Count": 558.0,
        "Location Phone": 14345849382.0,
        "Google Maps Url": "https://maps.google.com/?q=123",
    }


def test_normalize_row_produces_valid_lead() -> None:
    lead = normalize_row(_sample_row(), source_row_index=0)
    assert lead.phone_e164 == "+14345849382"
    assert lead.restaurant_name == "313Franklin"
    assert lead.state == "VA"  # full name normalized to 2-letter USPS code (varchar(2))
    assert lead.timezone == "America/New_York"  # tz still inferred from full "Virginia"
    assert lead.postal_code == "23970"
    assert lead.source_row_index == 0


def test_normalize_row_missing_phone_raises() -> None:
    row = _sample_row()
    row["Location Phone"] = float("nan")
    with pytest.raises(PhoneParseError):
        normalize_row(row, source_row_index=1)


def test_normalize_row_raw_metadata_has_contact_info() -> None:
    lead = normalize_row(_sample_row(), source_row_index=0)
    assert lead.raw_metadata["contact_first_name"] == "Kyle"
    assert lead.raw_metadata["contact_email"] == "kyle@example.com"


def test_normalize_row_nan_in_metadata_becomes_none() -> None:
    row = _sample_row()
    row["email"] = float("nan")
    lead = normalize_row(row, source_row_index=0)
    assert lead.raw_metadata["contact_email"] is None


def test_normalize_row_missing_postal_still_uses_state_tz() -> None:
    row = _sample_row()
    row["organization_postal_code"] = float("nan")
    lead = normalize_row(row, source_row_index=0)
    assert lead.timezone == "America/New_York"
    assert lead.postal_code is None
