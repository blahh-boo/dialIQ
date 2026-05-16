"""Tests for the FastAPI webhook receiver — no DB, no Anthropic, no Vapi required."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from maple.web.app import app
from maple.web.models import VapiEndOfCallReport

client = TestClient(app)

# ── sample payloads ───────────────────────────────────────────────────────────


def _end_of_call_payload(
    call_id: str = "call-abc-123",
    phone: str = "+14155551234",
    ended_reason: str = "assistant-ended-call",
    transcript: str = "Assistant: Hi.\nUser: Hello.",
) -> dict[str, Any]:
    return {
        "message": {
            "type": "end-of-call-report",
            "endedReason": ended_reason,
            "call": {
                "id": call_id,
                "customer": {"number": phone},
                "startedAt": "2024-01-01T12:00:00Z",
                "endedAt": "2024-01-01T12:02:00Z",
            },
            "transcript": transcript,
            "messages": [
                {"role": "assistant", "message": "Hi.", "time": 1.0},
                {"role": "user", "message": "Hello.", "time": 3.0},
            ],
        }
    }


def _status_update_payload(status: str = "ringing") -> dict[str, Any]:
    return {
        "message": {
            "type": "status-update",
            "status": status,
            "call": {
                "id": "call-abc-123",
                "customer": {"number": "+14155551234"},
            },
        }
    }


# ── health check ──────────────────────────────────────────────────────────────


def test_health_returns_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── secret validation ─────────────────────────────────────────────────────────


def test_no_secret_configured_allows_all() -> None:
    with patch("maple.web.app.get_settings") as mock_settings:
        mock_settings.return_value.vapi_webhook_secret = None
        resp = client.post("/vapi/webhook", json=_end_of_call_payload())
    assert resp.status_code == 200


def test_wrong_secret_returns_401() -> None:
    from pydantic import SecretStr

    with patch("maple.web.app.get_settings") as mock_settings:
        mock_settings.return_value.vapi_webhook_secret = SecretStr("correct-secret")
        resp = client.post(
            "/vapi/webhook",
            json=_end_of_call_payload(),
            headers={"x-vapi-secret": "wrong-secret"},
        )
    assert resp.status_code == 401


def test_correct_secret_returns_200() -> None:
    from pydantic import SecretStr

    with (
        patch("maple.web.app.get_settings") as mock_settings,
        patch("maple.web.app._process_end_of_call"),
    ):
        mock_settings.return_value.vapi_webhook_secret = SecretStr("correct-secret")
        resp = client.post(
            "/vapi/webhook",
            json=_end_of_call_payload(),
            headers={"x-vapi-secret": "correct-secret"},
        )
    assert resp.status_code == 200


# ── response shape ────────────────────────────────────────────────────────────


def test_end_of_call_returns_ok() -> None:
    with (
        patch("maple.web.app.get_settings") as mock_settings,
        patch("maple.web.app._process_end_of_call"),
    ):
        mock_settings.return_value.vapi_webhook_secret = None
        resp = client.post("/vapi/webhook", json=_end_of_call_payload())
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_status_update_returns_ok() -> None:
    with patch("maple.web.app.get_settings") as mock_settings:
        mock_settings.return_value.vapi_webhook_secret = None
        resp = client.post("/vapi/webhook", json=_status_update_payload())
    assert resp.status_code == 200


def test_unknown_message_type_returns_ok() -> None:
    with patch("maple.web.app.get_settings") as mock_settings:
        mock_settings.return_value.vapi_webhook_secret = None
        resp = client.post("/vapi/webhook", json={"message": {"type": "speech-update"}})
    assert resp.status_code == 200


def test_empty_body_returns_ok() -> None:
    with patch("maple.web.app.get_settings") as mock_settings:
        mock_settings.return_value.vapi_webhook_secret = None
        resp = client.post("/vapi/webhook", json={})
    assert resp.status_code == 200


# ── Vapi model parsing ────────────────────────────────────────────────────────


def test_vapi_end_of_call_report_parses_correctly() -> None:
    payload = _end_of_call_payload()["message"]
    report = VapiEndOfCallReport.model_validate(payload)
    assert report.call.id == "call-abc-123"
    assert report.call.customer.number == "+14155551234"
    assert report.ended_reason == "assistant-ended-call"
    assert report.transcript is not None
    assert len(report.messages) == 2


def test_vapi_report_computes_duration() -> None:
    payload = _end_of_call_payload()["message"]
    report = VapiEndOfCallReport.model_validate(payload)
    assert report.call.started_at is not None
    assert report.call.ended_at is not None
    delta = (report.call.ended_at - report.call.started_at).total_seconds()
    assert delta == 120.0


def test_vapi_report_missing_transcript_is_none() -> None:
    payload = _end_of_call_payload()["message"]
    del payload["transcript"]
    report = VapiEndOfCallReport.model_validate(payload)
    assert report.transcript is None


def test_vapi_report_extra_fields_ignored() -> None:
    payload = _end_of_call_payload()["message"]
    payload["recordingUrl"] = "https://example.com/recording.mp3"
    payload["summary"] = "The caller ordered food."
    report = VapiEndOfCallReport.model_validate(payload)
    assert report.call.id == "call-abc-123"
