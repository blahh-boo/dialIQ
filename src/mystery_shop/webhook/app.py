"""FastAPI app — one route: POST /vapi/webhook.

Vapi delivers end-of-call-report and status-update events here.
The handler acknowledges immediately (200 OK) and processes in a background task.
Idempotent: duplicate deliveries of the same vapi_call_id are silently ignored.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from mystery_shop.api.routes import router as api_router
from mystery_shop.config import get_settings
from mystery_shop.db.session import session_scope
from mystery_shop.llm.claude_client import ClaudeClient
from mystery_shop.webhook.pipeline import run_extraction_pipeline, upsert_call_attempt
from mystery_shop.webhook.vapi_models import VapiEndOfCallReport

logger = logging.getLogger(__name__)

app = FastAPI(title="Mystery Shop Webhook", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(api_router)


def _verify_secret(request: Request) -> None:
    """Reject requests that don't carry the configured Vapi webhook secret."""
    settings = get_settings()
    if settings.vapi_webhook_secret is None:
        return
    header_val = request.headers.get("x-vapi-secret", "")
    if header_val != settings.vapi_webhook_secret.get_secret_value():
        raise HTTPException(status_code=401, detail="invalid webhook secret")


def _process_end_of_call(payload: dict[str, Any]) -> None:
    """Parse, persist, and run extraction pipeline for an end-of-call-report.

    Runs in a background task after the 200 OK is sent to Vapi.
    Any exception here is logged but does not affect the HTTP response.
    """
    settings = get_settings()
    try:
        report = VapiEndOfCallReport.model_validate(payload)
    except ValidationError:
        logger.exception("Failed to parse end-of-call-report payload")
        return

    try:
        with session_scope() as session:
            attempt = upsert_call_attempt(report, session=session)
            if attempt is None:
                return  # unknown lead — already logged

        client = ClaudeClient(api_key=settings.anthropic_api_key.get_secret_value())
        with session_scope() as session:
            run_extraction_pipeline(report, attempt.id, session=session, client=client)

    except Exception:
        logger.exception(
            "Extraction pipeline failed for vapi_call_id=%s", payload.get("call", {}).get("id")
        )


@app.post("/vapi/webhook")
async def vapi_webhook(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    """Receive Vapi webhook events.

    Returns 200 immediately; processing happens in a background task.
    """
    _verify_secret(request)

    body: dict[str, Any] = await request.json()
    message: dict[str, Any] = body.get("message", {})
    msg_type: str = message.get("type", "")

    if msg_type == "end-of-call-report":
        background_tasks.add_task(_process_end_of_call, message)
    elif msg_type == "status-update":
        # Status updates (ringing, in-progress) are acknowledged but not stored.
        logger.debug("status-update: %s", message.get("status"))
    else:
        logger.debug("Ignoring unknown Vapi message type: %r", msg_type)

    return JSONResponse({"status": "ok"})


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
