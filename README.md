# Mystery Shop

Automated phone-based mystery shopping for restaurant leads. Places a takeout-order call via Vapi, extracts ten structured facts per call with Claude, scores each call deterministically, and outputs an SDR-ranked CSV.

The output for each restaurant is structured data — not a transcript dump — including a non-negotiable `pickup: bool`, a 0-100 numeric score, a HOT/WARM/COLD tier, and a one-line SDR brief.

## Architecture

```
xlsx (2,355 leads)
  └─► ingest:        pandas → phone E.164 → tz inference → leads table
                     dedup on phone (uq_leads_phone_e164), zip leading-zeros restored

leads (DB)
  └─► scheduler:     business hours (11-2 local), interleave (no back-to-back same #),
                     order by google_reviews_count DESC (more traffic = better signal)
       └─► pre-call: Sonnet infers cuisine_type + order_item from name/website
            └─► Vapi place_call (per-call assistantOverrides.variableValues)

[Restaurant answers / voicemails / hangs up]
  └─► Vapi end-of-call-report → FastAPI /vapi/webhook (idempotent on vapi_call_id)
       └─► extraction pipeline (background task):
            1. Haiku  classify answered_by (HUMAN/VOICEMAIL/IVR/...)
            2. Sonnet extract 10 CallFacts via strict tool use
            3. Python score_call(facts) → numeric_score + tier
            4. Haiku  one-line SDR brief
       └─► extractions + scores tables

ranked.csv ◄── export-ranked: HOT first, worst score first within tier
```

Five tables: `leads`, `call_attempts`, `transcripts`, `extractions`, `scores`. Full DDL in [migrations/versions/0001_initial.py](migrations/versions/0001_initial.py).

## Quick start

```bash
# one-time
brew install postgresql ngrok uv
createdb mysteryshop
uv sync
cp .env.example .env                   # add ANTHROPIC_API_KEY at minimum
uv run alembic upgrade head

# health check
uv run mystery-shop doctor

# load the leads xlsx (handles leading-zero zips, dedupes on phone, drops 40 no-phone rows)
uv run mystery-shop ingest "Restaurant Phone Numbers - Maple Take Home Round 2.xlsx"

# fire 20 calls (RUN_MODE drives the voice provider — default is mock)
uv run mystery-shop campaign --limit 20

# write the SDR deliverable
uv run mystery-shop export-ranked              # → samples/ranked.csv
```

## Run modes (env var `RUN_MODE`)

| Mode               | Voice provider                                        | Network?      | Use case                                      |
| ------------------ | ----------------------------------------------------- | ------------- | --------------------------------------------- |
| `mock` (default) | canned transcripts from `samples/transcripts/`      | Claude only   | Tests, CI, demos                              |
| `replay`         | same fixtures, treated as "real captured transcripts" | Claude only   | Prompt iteration without burning Vapi credits |
| `live`           | Vapi outbound calls                                   | Vapi + Claude | Real campaigns                                |

Live mode requires the four `VAPI_*` env vars (enforced by config validator).

## CLI

| Command                       | What it does                                                                                         |
| ----------------------------- | ---------------------------------------------------------------------------------------------------- |
| `doctor`                    | Verify env, DB, Anthropic key, Vapi config                                                           |
| `ingest <xlsx>`             | Load + normalize + dedupe leads                                                                      |
| `campaign --limit N`        | Fire N calls respecting business hours + interleave                                                  |
| `score --call-attempt-id N` | Re-score an existing call against the current rubric (upsert on `(extraction_id, rubric_version)`) |
| `replay <transcript.json>`  | Run the full LLM pipeline against a saved transcript; prints results,**no DB write**           |
| `export-ranked`             | Write `samples/ranked.csv` ranked by SDR priority                                                  |

## Webhook

`POST /vapi/webhook` — receives Vapi `end-of-call-report` and `status-update` events.

- Validates the `x-vapi-secret` header when `VAPI_WEBHOOK_SECRET` is set
- Returns 200 immediately; extraction runs in a `BackgroundTask`
- Idempotent: duplicate deliveries with the same `vapi_call_id` short-circuit on the partial unique index

## The 10 CallFacts (extraction shape)

Defined in [src/mystery_shop/llm/schemas.py](src/mystery_shop/llm/schemas.py). Strict tool use guarantees schema-valid output. Per-field confidence + evidence live in nested `ExtractionMetadata`.

**Scored** (fed into [src/mystery_shop/scoring/rubric.py](src/mystery_shop/scoring/rubric.py)):

1. `pickup: bool` — load-bearing; `False` is always HOT
2. `rings_to_answer: int | None`
3. `put_on_hold: bool`
4. `hold_time_seconds: int | None`
5. `transfer_count: int`
6. `call_abandoned_by_restaurant: bool` — `True` is always HOT
7. `interruption_count: int`
8. `repeated_information_count: int`
9. `upsell_attempted: bool` — positive signal (no deduction if True)
10. `customer_effort_score: int` — 1 (effortless) … 5 (very high effort)

**Observation** (SDR color, not scored):

- `key_failure_quote: str | None` — verbatim quote surfaced in the one-liner

## Scoring rubric

Pure Python — same `CallFacts` always produces the same `ScoreResult`. Score starts at 100, deductions subtracted, floored at 0. `RUBRIC_VERSION` is stored on every score row for auditability; bump it on any weight change. Full deduction table is in [CLAUDE.md](CLAUDE.md).

Tier thresholds: **HOT** = no pickup OR abandoned OR `score ≤ 40` · **WARM** = `41-70` · **COLD** = `≥ 71`.

## Cost estimate

Per-call breakdown lives in [samples/cost_log.json](samples/cost_log.json).

| Stage                            | Model      | Per-call (cached) |
| -------------------------------- | ---------- | ----------------- |
| Pre-call cuisine/order           | Sonnet 4.6 | $0.0017           |
| Answered-by classifier           | Haiku 4.5  | $0.0004           |
| CallFacts extractor              | Sonnet 4.6 | $0.0066           |
| SDR one-liner                    | Haiku 4.5  | $0.0004           |
| In-call agent + Vapi voice stack | Vapi       | ~$0.35            |
| **Total per call**         |            | **~$0.36**  |

Sample-run budget ceiling: **$20**. 20 calls projected at ~$7. Prompt caching (`cache_control: ephemeral` on system prompts) gives ~45% savings on the LLM portion at scale.

## Tradeoffs and what's deliberately out of scope

- **Timezone resolution is state-level when zip lookup fails.** Leads with `timezone=None` are silently skipped by the scheduler. State-spanning timezones (Indiana, Kentucky) use the dominant zone — fine for a ±1h call window.
- **One call per restaurant.** Retry logic isn't ours — Vapi handles voicemail backoff. Re-attempts would just rerun `ingest` after clearing `call_attempts`.
- **Mock and replay providers are functionally identical** (both read from `samples/transcripts/`). Kept as separate `RUN_MODE` values for spec clarity: mock = ships with canned fixtures; replay = drop your own captured transcripts in.
- **No menu scraping.** Cuisine/order item is LLM-inferred from name + website. Documented limitation.
- **No multi-tenancy, no auth on FastAPI.** Local-first, single operator.
- **No concurrent call rate limiting.** Sequential dispatch is fine for 2,355 leads over a few hours.
- **Recording consent is verbal in `firstMessage`.** Some two-party states need more — documented as a known limitation.

## Data quality notes

The xlsx has the anomalies you'd expect from a CRM export. The ingest handles them:

- 40 rows missing a phone number → counted as `skipped_no_phone`
- 217 phone numbers duplicated 2-4× (same restaurant, different contacts) → deduped on the unique constraint
- 112 zip codes truncated by Excel's float64 typing (e.g. NJ `07030` → `7030.0` → `0`) → `_normalize_postal_code` zero-pads to 5 digits
- `Unnamed: 3` column is 100% null → dropped at ingest

See [explore_leads.ipynb](explore_leads.ipynb) for the visual walkthrough.

## Tests / lint / types

```bash
uv run ruff check && uv run ruff format --check
uv run mypy src
uv run pytest
```

167 tests across 9 files. Zero infrastructure dependency — no DB, no network. Mock voice provider + canned transcripts cover the full pipeline.

## Project layout

```
src/mystery_shop/
├── cli.py                  # typer subcommands (doctor, ingest, campaign, ...)
├── config.py               # pydantic-settings, RUN_MODE validation
├── db/
│   ├── models.py           # 5 SQLAlchemy models (Mapped/mapped_column)
│   └── session.py          # session_scope() commit-on-success
├── ingest/
│   ├── normalize.py        # phone E.164, zip zero-pad, tz inference
│   └── xlsx_loader.py      # pandas → leads (idempotent via on_conflict_do_nothing)
├── voice/
│   ├── base.py             # VoiceProvider Protocol + Pydantic IO models
│   ├── mock_provider.py    # delegates to ReplayProvider over samples/transcripts/
│   ├── replay_provider.py  # cycles through transcript JSONs
│   └── vapi_provider.py    # real outbound calls
├── llm/
│   ├── claude_client.py    # thin Anthropic wrapper with prompt caching
│   ├── precall.py          # Sonnet: cuisine_type + order_item
│   ├── classifier.py       # Haiku: answered_by
│   ├── extractor.py        # Sonnet: 10 CallFacts via strict tool use
│   ├── summarizer.py       # Haiku: one-line SDR brief
│   ├── prompts/            # versioned .txt files (filename stored on each extraction row)
│   └── schemas.py          # CallFacts, ScoreResult, ExtractionMetadata
├── scoring/
│   ├── rubric.py           # pure function — same input → same output
│   └── tiers.py            # HOT/WARM/COLD thresholds
├── scheduling/
│   ├── business_hours.py   # 11am-2pm local window
│   ├── interleave.py       # don't dial the same number twice in a row
│   └── worker.py           # campaign loop: classify → extract → score → summarize
├── webhook/
│   ├── app.py              # FastAPI: POST /vapi/webhook, GET /health
│   ├── pipeline.py         # same 4-pass extraction, async path
│   └── vapi_models.py      # Pydantic models for the incoming Vapi payload
└── export/
    └── ranked_csv.py       # final SDR deliverable
```
