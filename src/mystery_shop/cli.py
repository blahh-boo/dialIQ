"""CLI entry point. All subcommands live here."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    name="mystery-shop",
    help="Mystery shopping system for restaurant phone experience.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def doctor() -> None:
    """Verify env, DB connectivity, and required API credentials are configured."""
    from pydantic import ValidationError
    from sqlalchemy import text

    from mystery_shop.config import RunMode, get_settings
    from mystery_shop.db.session import session_scope

    def ok(label: str, detail: str = "") -> None:
        typer.echo(f"  [OK]   {label}" + (f" — {detail}" if detail else ""))

    def fail(label: str, detail: str) -> None:
        typer.echo(f"  [FAIL] {label} — {detail}", err=True)

    failures = 0

    try:
        settings = get_settings()
        ok("env loaded", f"run_mode={settings.run_mode}")
    except ValidationError as exc:
        fail("env", f"missing/invalid: {exc.errors()[0]['loc']}")
        raise typer.Exit(1) from exc

    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
        ok("postgres", settings.database_url.rsplit("@", 1)[-1])
    except Exception as exc:
        fail("postgres", str(exc).splitlines()[0])
        failures += 1

    if settings.anthropic_api_key.get_secret_value().startswith("sk-ant-"):
        ok("anthropic key", "present")
    else:
        fail("anthropic key", "missing or wrong format")
        failures += 1

    if settings.run_mode is RunMode.LIVE:
        missing = [
            name
            for name, val in (
                ("VAPI_API_KEY", settings.vapi_api_key),
                ("VAPI_PHONE_NUMBER_ID", settings.vapi_phone_number_id),
                ("VAPI_ASSISTANT_ID", settings.vapi_assistant_id),
                ("VAPI_WEBHOOK_SECRET", settings.vapi_webhook_secret),
            )
            if not val
        ]
        if missing:
            fail("vapi config", f"missing: {', '.join(missing)}")
            failures += 1
        else:
            ok("vapi config", "all live-mode keys present")

    if failures:
        raise typer.Exit(1)


@app.command()
def ingest(xlsx_path: str) -> None:
    """Load + normalize a lead list from xlsx into the leads table."""
    from mystery_shop.db.session import session_scope
    from mystery_shop.ingest.xlsx_loader import load_xlsx

    path = Path(xlsx_path)
    if not path.exists():
        typer.echo(f"File not found: {path}", err=True)
        raise typer.Exit(1)

    with session_scope() as session:
        result = load_xlsx(path, session)

    typer.echo(
        f"Done — inserted: {result.inserted}, duplicates: {result.skipped_duplicate}, "
        f"no_phone: {result.skipped_no_phone}, errors: {result.error_count}"
    )


@app.command()
def campaign(limit: int = typer.Option(..., "--limit", help="Max calls to place")) -> None:
    """Fire up to N calls respecting business hours and interleave rules."""
    from mystery_shop.config import RunMode, get_settings
    from mystery_shop.db.session import session_scope
    from mystery_shop.llm.claude_client import ClaudeClient
    from mystery_shop.scheduling.worker import run_campaign
    from mystery_shop.voice.base import VoiceProvider

    settings = get_settings()
    client = ClaudeClient(settings.anthropic_api_key.get_secret_value())

    provider: VoiceProvider
    if settings.run_mode is RunMode.LIVE:
        from mystery_shop.voice.vapi_provider import VapiProvider

        provider = VapiProvider(
            api_key=settings.vapi_api_key.get_secret_value(),  # type: ignore[union-attr]
            phone_number_id=settings.vapi_phone_number_id or "",
        )
        assistant_id = settings.vapi_assistant_id or ""
    elif settings.run_mode is RunMode.REPLAY:
        from mystery_shop.voice.replay_provider import ReplayProvider

        provider = ReplayProvider(transcripts_dir=Path("samples/transcripts"))
        assistant_id = "replay"
    else:
        from mystery_shop.voice.mock_provider import MockProvider

        provider = MockProvider()
        assistant_id = "mock"

    typer.echo(f"Campaign starting — limit={limit}, mode={settings.run_mode}")

    with session_scope() as session:
        result = run_campaign(
            limit=limit,
            session=session,
            voice_provider=provider,
            client=client,
            assistant_id=assistant_id,
        )

    typer.echo(
        f"Done — called: {result.called}, "
        f"skipped_hours: {result.skipped_hours}, "
        f"skipped_queue: {result.skipped_queue}"
    )


@app.command()
def score(call_attempt_id: int = typer.Option(..., "--call-attempt-id")) -> None:
    """Re-score an existing call attempt against the current rubric."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from mystery_shop.db.models import CallAttempt, Extraction, Score
    from mystery_shop.db.session import session_scope
    from mystery_shop.llm.schemas import CallFacts
    from mystery_shop.scoring.rubric import RUBRIC_VERSION, score_call

    with session_scope() as session:
        attempt = session.get(CallAttempt, call_attempt_id)
        if attempt is None:
            typer.echo(f"No call_attempt with id={call_attempt_id}", err=True)
            raise typer.Exit(1)

        extraction = (
            session.query(Extraction)
            .filter_by(call_attempt_id=call_attempt_id)
            .order_by(Extraction.id.desc())
            .first()
        )
        if extraction is None:
            typer.echo(f"No extraction for call_attempt_id={call_attempt_id}", err=True)
            raise typer.Exit(1)

        facts = CallFacts.model_validate(extraction.fields_jsonb)
        result = score_call(facts)

        session.execute(
            pg_insert(Score)
            .values(
                extraction_id=extraction.id,
                pickup=result.pickup,
                numeric_score=result.numeric_score,
                tier=result.tier,
                rubric_version=RUBRIC_VERSION,
            )
            .on_conflict_do_update(
                constraint="uq_scores_extraction_rubric",
                set_={
                    "pickup": result.pickup,
                    "numeric_score": result.numeric_score,
                    "tier": result.tier,
                },
            )
        )

    typer.echo(f"Score: {result.numeric_score}/100  Tier: {result.tier}  Pickup: {result.pickup}")
    for d in result.deductions:
        typer.echo(f"  -{d.points:>3}  {d.reason}")


@app.command()
def replay(transcript_path: str) -> None:
    """Run the full extraction pipeline against a saved transcript JSON (no DB write)."""
    from mystery_shop.config import get_settings
    from mystery_shop.llm.classifier import classify_answered_by
    from mystery_shop.llm.claude_client import ClaudeClient
    from mystery_shop.llm.extractor import extract_call_facts
    from mystery_shop.llm.summarizer import generate_one_liner
    from mystery_shop.scoring.rubric import score_call
    from mystery_shop.voice.base import EndOfCallReport

    path = Path(transcript_path)
    if not path.exists():
        typer.echo(f"File not found: {path}", err=True)
        raise typer.Exit(1)

    settings = get_settings()
    client = ClaudeClient(settings.anthropic_api_key.get_secret_value())

    report = EndOfCallReport.model_validate_json(path.read_text())
    typer.echo(f"Transcript ({report.duration_seconds}s): {report.transcript_text[:120]}...")
    typer.echo("")

    answered_by = classify_answered_by(report.transcript_text, client=client)
    typer.echo(f"Answered by:  {answered_by}")

    facts = extract_call_facts(report, answered_by=answered_by, client=client)
    typer.echo(f"Pickup:       {facts.pickup}")
    typer.echo(f"CES:          {facts.customer_effort_score}/5")
    typer.echo(f"Hold:         {facts.put_on_hold} ({facts.hold_time_seconds}s)")
    typer.echo(f"Transfers:    {facts.transfer_count}")
    typer.echo(f"Interrupts:   {facts.interruption_count}")
    typer.echo(f"Repeats:      {facts.repeated_information_count}")
    if facts.key_failure_quote:
        typer.echo(f'Key quote:    "{facts.key_failure_quote}"')
    typer.echo("")

    result = score_call(facts)
    typer.echo(f"Score: {result.numeric_score}/100  Tier: {result.tier}")
    for d in result.deductions:
        typer.echo(f"  -{d.points:>3}  {d.reason}")
    typer.echo("")

    one_liner = generate_one_liner(facts, result, client=client)
    typer.echo(f"SDR one-liner: {one_liner}")


@app.command()
def reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
) -> None:
    """Wipe all call data (call_attempts → transcripts → extractions → scores).

    Leaves the `leads` table untouched. Idempotent: running it twice is identical
    to running it once. Used by `make seed` to guarantee a deterministic state.

    Safety: refuses to run non-interactively (`--yes`) against a non-local
    database, so an automated seed can never truncate a remote/prod DB.
    """
    from urllib.parse import urlparse

    from sqlalchemy import func, text

    from mystery_shop.config import get_settings
    from mystery_shop.db.models import CallAttempt, Extraction, Score, Transcript
    from mystery_shop.db.session import session_scope

    settings = get_settings()

    # Guard: never allow unattended truncation of a non-local database.
    # Strip the SQLAlchemy "+driver" suffix so urlparse can read the host.
    dsn = settings.database_url
    scheme, _, rest = dsn.partition("://")
    normalized = scheme.split("+", 1)[0] + "://" + rest
    host = (urlparse(normalized).hostname or "").lower()
    is_local = host in ("", "localhost", "127.0.0.1", "::1")
    if not is_local and yes:
        typer.echo(
            f"Refusing: --yes against non-local DB host {host!r}. "
            "Run without --yes to confirm interactively.",
            err=True,
        )
        raise typer.Exit(1)

    with session_scope() as session:
        counts = {
            "call_attempts": session.query(func.count(CallAttempt.id)).scalar() or 0,
            "transcripts": session.query(func.count(Transcript.id)).scalar() or 0,
            "extractions": session.query(func.count(Extraction.id)).scalar() or 0,
            "scores": session.query(func.count(Score.id)).scalar() or 0,
        }

    total = sum(counts.values())
    if total == 0:
        typer.echo("Nothing to reset — call data is already empty.")
        return

    summary = ", ".join(f"{n} {t}" for t, n in counts.items() if n)
    if not yes:
        typer.echo(f"This will permanently delete: {summary}.")
        typer.echo(f"Leads are NOT affected. Database host: {host or 'local socket'}.")
        if not typer.confirm("Proceed?"):
            typer.echo("Aborted — nothing changed.")
            raise typer.Exit(1)

    # One transaction. session_scope commits on success, rolls back on any error —
    # a failure mid-truncate leaves the DB exactly as it was.
    with session_scope() as session:
        session.execute(text("TRUNCATE TABLE call_attempts RESTART IDENTITY CASCADE"))

    typer.echo(f"Reset complete — deleted {summary}. Leads preserved.")


@app.command(name="export-ranked")
def export_ranked(
    output: str = typer.Option("samples/ranked.csv", "--output", "-o"),
) -> None:
    """Write ranked.csv sorted by SDR priority (HOT first, worst score first)."""
    from mystery_shop.db.session import session_scope
    from mystery_shop.export.ranked_csv import write_ranked_csv

    output_path = Path(output)
    with session_scope() as session:
        count = write_ranked_csv(session, output_path)

    typer.echo(f"Wrote {count} rows → {output_path}")


if __name__ == "__main__":
    app()
