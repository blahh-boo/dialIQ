"""Tests for voice providers — no network required."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mystery_shop.voice.base import EndOfCallReport, PlacedCall, VoiceProvider
from mystery_shop.voice.mock_provider import MockProvider
from mystery_shop.voice.replay_provider import ReplayProvider

_FIXTURES = Path(__file__).parent.parent / "samples" / "transcripts"

_CALL_KWARGS: dict[str, object] = {
    "to": "+14155551234",
    "assistant_id": "asst-test",
    "variables": {
        "restaurant_name": "Golden Dragon",
        "cuisine_type": "Chinese",
        "order_item": "fried rice",
    },
}


# ── MockProvider ──────────────────────────────────────────────────────────────


def test_mock_provider_satisfies_protocol() -> None:
    assert isinstance(MockProvider(), VoiceProvider)


def test_mock_place_call_returns_placed_call() -> None:
    result = MockProvider().place_call(**_CALL_KWARGS)  # type: ignore[arg-type]
    assert isinstance(result, PlacedCall)
    assert result.vapi_call_id.startswith("mock-")
    assert result.report is not None


def test_mock_report_has_required_fields() -> None:
    report = MockProvider().place_call(**_CALL_KWARGS).report  # type: ignore[arg-type]
    assert report is not None
    assert report.call_id
    assert report.ended_reason
    assert report.transcript_text
    assert len(report.messages) > 0
    assert report.duration_seconds >= 0


def test_mock_cycles_through_scenarios() -> None:
    provider = MockProvider()
    results = [provider.place_call(**_CALL_KWARGS).report for _ in range(8)]  # type: ignore[arg-type]
    # Should cycle; first 4 are unique, next 4 repeat
    ids = [r.call_id if r else None for r in results]
    assert ids[:4] == ids[4:8]


def test_mock_cycle_covers_all_scenarios() -> None:
    provider = MockProvider()
    reports = [provider.place_call(**_CALL_KWARGS).report for _ in range(4)]  # type: ignore[arg-type]
    ids = {r.call_id for r in reports if r is not None}
    assert ids == {"good-pickup-001", "voicemail-001", "hold-transfer-001", "abandoned-001"}


# ── ReplayProvider ────────────────────────────────────────────────────────────


def test_replay_provider_satisfies_protocol() -> None:
    assert isinstance(ReplayProvider(_FIXTURES), VoiceProvider)


def test_replay_loads_fixture_file() -> None:
    provider = ReplayProvider(_FIXTURES)
    result = provider.place_call(**_CALL_KWARGS)  # type: ignore[arg-type]
    assert isinstance(result, PlacedCall)
    assert result.report is not None
    assert result.vapi_call_id.startswith("replay-")


def test_replay_cycles_through_files() -> None:
    provider = ReplayProvider(_FIXTURES)
    n = len(sorted(_FIXTURES.glob("*.json")))
    ids = [provider.place_call(**_CALL_KWARGS).vapi_call_id for _ in range(n * 2)]  # type: ignore[arg-type]
    assert ids[:n] == ids[n:]


def test_replay_raises_on_empty_dir(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No transcript JSON files"):
        ReplayProvider(tmp_path)


def test_replay_invalid_json_raises(tmp_path: Path) -> None:
    from pydantic import ValidationError

    (tmp_path / "bad.json").write_text('{"call_id": "x"}')  # missing required fields
    with pytest.raises(ValidationError):
        ReplayProvider(tmp_path).place_call(**_CALL_KWARGS)  # type: ignore[arg-type]


# ── Fixture files ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "filename", ["good_pickup.json", "voicemail.json", "hold_and_transfer.json", "abandoned.json"]
)
def test_fixture_file_is_valid_end_of_call_report(filename: str) -> None:
    path = _FIXTURES / filename
    data = json.loads(path.read_text())
    report = EndOfCallReport.model_validate(data)
    assert report.call_id
    assert len(report.messages) > 0
    assert report.duration_seconds >= 0


def test_good_pickup_fixture_has_upsell() -> None:
    data = json.loads((_FIXTURES / "good_pickup.json").read_text())
    report = EndOfCallReport.model_validate(data)
    combined = " ".join(m.message for m in report.messages if m.role == "user").lower()
    assert "egg roll" in combined or "drink" in combined


def test_voicemail_fixture_ended_reason() -> None:
    data = json.loads((_FIXTURES / "voicemail.json").read_text())
    report = EndOfCallReport.model_validate(data)
    assert report.ended_reason == "voicemail"


def test_hold_transfer_fixture_has_hold_signal() -> None:
    data = json.loads((_FIXTURES / "hold_and_transfer.json").read_text())
    report = EndOfCallReport.model_validate(data)
    assert any("hold" in m.message.lower() for m in report.messages)
    assert any("transfer" in m.message.lower() for m in report.messages)
