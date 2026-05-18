"""Tests for voice providers — no network required."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from maple.voice import (
    EndOfCallReport,
    MockProvider,
    PlacedCall,
    ReplayProvider,
    VoiceProvider,
    _call_to_report,
)

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
    n = len(list(_FIXTURES.glob("*.json")))
    results = [provider.place_call(**_CALL_KWARGS).report for _ in range(n * 2)]  # type: ignore[arg-type]
    ids = [r.call_id if r else None for r in results]
    assert ids[:n] == ids[n:]  # one full cycle repeats exactly


def test_mock_cycle_covers_all_scenarios() -> None:
    provider = MockProvider()
    n = len(list(_FIXTURES.glob("*.json")))
    reports = [provider.place_call(**_CALL_KWARGS).report for _ in range(n)]  # type: ignore[arg-type]
    ids = {r.call_id for r in reports if r is not None}
    # The 4 core canned fixtures must always be present; real captured transcripts
    # may also appear and are valid additions to the fixture pool.
    assert {"good-pickup-001", "voicemail-001", "hold-transfer-001", "abandoned-001"}.issubset(ids)


# ── ReplayProvider ────────────────────────────────────────────────────────────


def test_replay_provider_satisfies_protocol() -> None:
    assert isinstance(ReplayProvider(_FIXTURES), VoiceProvider)


def test_replay_loads_fixture_file() -> None:
    provider = ReplayProvider(_FIXTURES)
    result = provider.place_call(**_CALL_KWARGS)  # type: ignore[arg-type]
    assert isinstance(result, PlacedCall)
    assert result.report is not None
    assert result.vapi_call_id.startswith("replay-")


def test_replay_cycles_transcripts_with_unique_ids() -> None:
    provider = ReplayProvider(_FIXTURES)
    n = len(sorted(_FIXTURES.glob("*.json")))
    placed = [provider.place_call(**_CALL_KWARGS) for _ in range(n * 2)]  # type: ignore[arg-type]

    # Transcript content cycles every n calls (same fixtures, in order)...
    report_ids = [p.report.call_id for p in placed if p.report]
    assert report_ids[:n] == report_ids[n:]

    # ...but every placed call has a UNIQUE vapi_call_id (DB constraint).
    call_ids = [p.vapi_call_id for p in placed]
    assert len(set(call_ids)) == len(call_ids)


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


# ── _call_to_report: Vapi calls.get() → EndOfCallReport mapping ───────────────


def _fake_msg(**kw: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "role": "user",
        "message": "hi",
        "seconds_from_start": 0.0,
        "duration": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _fake_call(**kw: object) -> SimpleNamespace:
    artifact = SimpleNamespace(
        transcript=kw.pop("transcript", "User: hi\nAI: hello"),
        messages=kw.pop("messages", [_fake_msg()]),
    )
    base: dict[str, object] = {
        "id": "call-abc",
        "ended_reason": "customer-ended-call",
        "started_at": datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
        "ended_at": datetime(2024, 6, 15, 12, 1, 30, tzinfo=UTC),
        "artifact": artifact,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_call_to_report_maps_core_fields() -> None:
    report = _call_to_report(_fake_call())
    assert report.call_id == "call-abc"
    assert report.ended_reason == "customer-ended-call"
    assert report.transcript_text == "User: hi\nAI: hello"
    assert report.duration_seconds == 90  # 12:01:30 minus 12:00:00


def test_call_to_report_uses_seconds_from_start_for_time() -> None:
    msgs = [_fake_msg(role="bot", message="Thanks for calling", seconds_from_start=4.2, duration=1.1)]
    report = _call_to_report(_fake_call(messages=msgs))
    assert len(report.messages) == 1
    assert report.messages[0].role == "bot"
    assert report.messages[0].time == 4.2
    assert report.messages[0].duration == 1.1


def test_call_to_report_skips_textless_messages() -> None:
    msgs = [
        _fake_msg(message="real turn"),
        _fake_msg(message=None),  # tool-call style — no transcript text
        SimpleNamespace(role="tool_calls"),  # missing message attr entirely
    ]
    report = _call_to_report(_fake_call(messages=msgs))
    assert [m.message for m in report.messages] == ["real turn"]


def test_call_to_report_handles_sparse_call() -> None:
    # Early-terminated call: no artifact, no timestamps.
    sparse = SimpleNamespace(
        id="call-x", ended_reason="no-answer", artifact=None, started_at=None, ended_at=None
    )
    report = _call_to_report(sparse)
    assert report.transcript_text == ""
    assert report.messages == ()
    assert report.duration_seconds == 0
