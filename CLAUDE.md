# Mystery Shopping System — Project Context

## What this is

A  AI phone-answering service for restaurants. This system mystery-shops prospective restaurant leads by placing automated phone calls, simulating a customer trying to place a takeout order, and producing **structured, SDR-actionable data** about each restaurant's phone experience.

Output for each call: structured data (not transcript dumps), including a non-negotiable `pickup: bool`, a 0-100 numeric score, a HOT/WARM/COLD tier, and a one-line SDR read.

## Hard constraints

- **Local-first.** SQLite by default (zero-install). Postgres is a one-line DSN swap, no code changes. FastAPI on localhost. ngrok only needed for webhook-based live campaigns (not for `make call`, which polls). No Docker.
- **Anthropic API for all LLM work.** No OpenAI, no other providers in the pipeline.
- **Extraction must be separate from scoring.** LLM produces observations; pure-Python scores them.
- **`pickup: bool` is the load-bearing field.** Every other rubric dimension is downstream of it.
- **Bail-before-commit.** The agent must never finalize an order. Hard requirement for restaurant ethics.
- **UI is a key part of the final deliverable**, but is being designed/built separately and will land later. For now, build the backend with a clean API surface that a frontend can hang off (well-typed endpoints, stable response shapes, no logic trapped in CLI commands). Do not scaffold UI code in this repo yet — wait for the frontend spec.

## Tech stack

| Layer         | Choice                                 | Version pin   |
| ------------- | -------------------------------------- | ------------- |
| Language      | Python                                 | 3.11+         |
| Web framework | FastAPI                                | latest        |
| Database      | SQLite (default) / Postgres (DSN swap) | —            |
| ORM           | SQLAlchemy                             | 2.0.49        |
| Voice         | Vapi (vapi-server-sdk)                 | 1.9.0         |
| LLM           | Anthropic SDK (`anthropic`)          | 0.102.0       |
| Validation    | Pydantic                               | 2.x           |
| Data ingest   | pandas + openpyxl                      | latest        |
| Tunneling     | ngrok (static domain)                  | —            |
| Timezone      | pgeocode + timezonefinder              | 0.5.0 / 8.2.4 |

## Models used

- **Pre-call (script + cuisine inference):** `claude-sonnet-4-6` — cheap, creative, med-stakes
- **Post-call classification (was it voicemail?):** `claude-haiku-4-5` — cheap two-pass
- **Post-call extraction (15-field CallFacts):** `claude-sonnet-4-6` — accuracy matters
- **Post-call SDR one-liner:** `claude-haiku-4-5` — short output, easy task
- **In-call agent (Vapi-side):** `claude-haiku-4-5` — fast turn latency

## Architecture

```
xlsx lead list
   ↓ (pandas ingest, normalize phones, infer timezone)
DB: leads table (SQLite default; Postgres = change DSN)
   ↓ (scheduler: business hours, no-answer retry, google_reviews_count priority)
Pre-call: Haiku infers cuisine_type + order_item from name/website
   ↓
Vapi POST /call with assistantOverrides.variableValues
   ↓
[Restaurant answers]
   ↓
Two result paths:
  A) make call / make campaign-live → polls calls.get() (no webhook needed)
  B) make campaign-live with webhook → FastAPI /vapi/webhook → background task
   ↓
DB: call_attempts + transcripts tables
   ↓
Extraction pipeline:
   ├─ Haiku Pass 1: answered_by classifier (HUMAN/VOICEMAIL/IVR/...)
   ├─ Sonnet Pass 2: 10-field strict-tool-use CallFacts extraction
   └─ Deterministic Python scorer → score + tier
   ↓
Haiku: generates SDR one-liner from facts + score
   ↓
DB: extractions + scores tables
   ↓
ranked.csv export → the deliverable
```

## Three run modes (toggle via env var)

```bash
RUN_MODE=live      # Real Vapi + real Claude. Use sparingly.
RUN_MODE=replay    # Saved transcripts → real Claude. Default for dev.
RUN_MODE=mock      # Canned fixtures → no network. For unit tests / CI.
```

`replay` mode is critical — make 5-6 real calls early, save the transcripts as fixtures in `samples/transcripts/`, then iterate the extraction prompt thousands of times without burning credits.

## Repo structure

```
Maple/
├── CLAUDE.md                   # this file
├── README.md                   # for the reviewer (incl. Operations section)
├── .env.example
├── Makefile                    # setup / seed / api / ui / reset / call / campaign-live / mock
├── scripts/                    # setup.sh, seed.sh (guarded provisioning/seeding)
├── pyproject.toml
├── data.xlsx                   # the lead list
├── frontend/                   # Vite + React + TS SDR cockpit
├── samples/
│   ├── transcripts/            # canned fixtures (mock/replay + tests)
│   ├── ranked.csv
│   └── cost_log.json
└── maple/                      # the package (no src/ wrapper, no Alembic)
    ├── __init__.py
    ├── cli.py                  # typer: doctor, init-db, ingest, campaign, call, score, replay, reset, export-ranked
    ├── config.py               # env vars, run mode
    ├── db.py                   # 5 SQLAlchemy models + session_scope() + init_db()
    ├── ingest.py               # phone E.164, zip, tz + state norm, xlsx → leads
    ├── voice.py                # VoiceProvider Protocol + mock / replay / live Vapi
    ├── scoring.py              # score_call(facts) → ScoreResult + tier thresholds
    ├── scheduling.py           # business hours + interleave + campaign loop
    ├── export.py               # ranked.csv deliverable
    ├── llm/
    │   ├── client.py           # thin Anthropic SDK wrapper (prompt caching)
    │   ├── schemas.py          # Pydantic CallFacts, ScoreResult, etc.
    │   ├── extractor.py        # Sonnet 10-field strict tool-use (the heavy pass)
    │   ├── passes.py           # precall + Haiku classifier + Haiku one-liner
    │   └── prompts/            # versioned .txt files
    └── web/
        ├── app.py              # FastAPI: POST /vapi/webhook, GET /health, mounts /api
        ├── routes.py           # /api/* cockpit endpoints
        ├── pipeline.py         # webhook-path extraction pipeline
        └── models.py           # Vapi payloads + cockpit API response schemas
```

## Database schema (5 tables)

- `leads` — restaurants from xlsx, with normalized phone, timezone, cuisine_type
- `call_attempts` — one row per dial attempt; status, vapi_call_id, ended_reason
- `transcripts` — raw_jsonb + plaintext
- `extractions` — fields_jsonb (the 15 CallFacts) + model_used + prompt_version
- `scores` — pickup, numeric_score, tier, summary_one_liner

Models + schema bootstrap in `maple/db.py` (`init_db()` — no Alembic).

## The CallFacts schema (extraction output)

Defined as a Pydantic model in `maple/llm/schemas.py`. Non-boolean fields carry paired confidence + evidence in nested `ExtractionMetadata`. Strict tool use guarantees schema-valid output.

**Scored fields** (fed directly into `rubric.py`):

1. `pickup: bool` — load-bearing; always HOT if False
2. `rings_to_answer: int | None` — from Vapi metadata
3. `put_on_hold: bool`
4. `hold_time_seconds: int | None`
5. `transfer_count: int`
6. `call_abandoned_by_restaurant: bool` — always HOT if True
7. `interruption_count: int`
8. `repeated_information_count: int`
9. `upsell_attempted: bool` — positive signal (no deduction if True)
10. `customer_effort_score: int` — 1 (effortless) to 5 (very high effort); LLM-produced gestalt

**Observation field** (SDR color, not scored):

- `key_failure_quote: str | None` — verbatim quote for SDR one-liner

## Scoring rubric (deterministic Python)

Pure function. Same `CallFacts` always produces the same `ScoreResult`. Rubric in `maple/scoring.py`. Score starts at 100, deductions subtracted, floored at 0. Bump `RUBRIC_VERSION` on any weight change.

Tier thresholds:

- **HOT:** `pickup == False` OR `call_abandoned_by_restaurant == True` OR `score ≤ 40`
- **WARM:** `41 ≤ score ≤ 70`
- **COLD:** `score ≥ 71`

Deduction table (v2):

| Signal                           | Condition   | Points                         |
| -------------------------------- | ----------- | ------------------------------ |
| `rings_to_answer`              | unknown     | 0 (absent evidence ≠ bad)     |
|                                  | 3-4 rings   | -5                             |
|                                  | 5+ rings    | -10                            |
| `put_on_hold`                  | True (base) | -5                             |
| `hold_time_seconds`            | 31-60s      | -5                             |
|                                  | 61-120s     | -12                            |
|                                  | 121s+       | -20                            |
| `transfer_count`               | 1           | -12                            |
|                                  | 2           | -20                            |
|                                  | 3+          | -30                            |
| `call_abandoned_by_restaurant` | True        | -30 + HOT override             |
| `interruption_count`           | 1-2         | -8                             |
|                                  | 3-4         | -15                            |
|                                  | 5+          | -20                            |
| `repeated_information_count`   | 1           | -10                            |
|                                  | 2           | -18                            |
|                                  | 3+          | -25                            |
| `upsell_attempted`             | False       | 0 (normal call, not a failure) |
| `customer_effort_score`        | 3           | -8                             |
|                                  | 4           | -15                            |
|                                  | 5           | -22                            |

## Conventions

- **Prompts live in `maple/llm/prompts/`** as versioned files (e.g., `extractor_v3.txt`). Never inline prompt strings in Python. Store the filename in `extractions.prompt_version` for auditability.
- **All LLM calls use prompt caching** (`cache_control: {"type": "ephemeral"}`) on the system prompt. ~85% cost reduction at scale.
- **Pydantic models everywhere.** No raw dicts crossing module boundaries.
- **All times stored as `TIMESTAMPTZ` UTC.** Convert to local only at display.
- **Phone numbers stored as E.164 strings.** Validate with `phonenumbers` library.
- **No secrets in code or migrations.** Everything via `.env`.
- **Idempotent webhook handler.** `vapi_call_id` is unique-where-not-null; duplicate `end-of-call-report` deliveries must not double-write.

## Local setup commands

Package management is **uv** (PEP 735 dependency groups). Lint/format **ruff**, types **mypy --strict**, tests **pytest**. Pre-commit hooks run all three locally on every commit.

### The easy path — four `make` targets

This is the canonical way to run the system. Prefer it; only drop to raw CLI for debugging.

```bash
# one-time install + secrets
brew install ngrok uv          # no database server — SQLite is the default
uv sync && npm --prefix frontend install
cp .env.example .env                 # then put a real ANTHROPIC_API_KEY in .env
uv run pre-commit install

make setup     # create schema + doctor   (run once)
make seed      # deterministic demo data — re-run-safe         (run anytime)
make api       # backend  (terminal 1) → http://localhost:8000
make ui        # frontend (terminal 2) → http://localhost:5173

# live call (single number, no ngrok needed)
make call NUMBER=+1XXXXXXXXXX
# live campaign (full lead list, needs ngrok + webhook)
make campaign-live LIMIT=20
# mock/offline
make mock
```

Raw CLI (what the targets wrap — for debugging)

```bash
# one-time (SQLite — no createdb needed)
uv run mystery-shop init-db                            # creates maple.db from models

# dev loop
uv run uvicorn maple.web.app:app --reload              # terminal 1
uv run mystery-shop doctor                             # health check
uv run mystery-shop ingest data.xlsx                   # load leads
uv run mystery-shop reset                              # wipe call data (keeps leads)
uv run mystery-shop campaign --limit 20                # mock calls
RUN_MODE=live uv run mystery-shop call --to +1XXX...  # one real call (polling, no ngrok)
uv run mystery-shop export-ranked                      # write samples/ranked.csv

# quality gates
uv run ruff check && uv run ruff format --check
uv run mypy maple
uv run pytest
```

## CLI commands

- `doctor` — verify env, DB, Anthropic auth, and (live mode) Vapi config
- `ingest <xlsx>` — load + normalize lead list
- `campaign --limit N` — fire N calls respecting business hours + interleave + no-answer retry
- `call --to <e164>` — place ONE real call, poll until done, run pipeline; `--save-fixture` to capture transcript
- `reset [--yes]` — wipe call data (call_attempts → … → scores), keep leads; refuses `--yes` on a non-local DB
- `score --call-attempt-id N` — re-score an existing call (rubric iteration)
- `replay <transcript.json>` — run the extraction pipeline against a saved transcript (no DB write)
- `export-ranked` — write `ranked.csv` for SDR consumption

> The four `make` targets (`setup`, `seed`, `api`, `ui`) wrap these — see **Local setup commands**.

## Build order

1. **Repo scaffold + pyproject.toml + .env.example**
2. **DB models + `init_db()`** — get `mystery-shop init-db` building the schema clean
3. **xlsx ingest** — load 2,355 leads, normalize phones, infer timezones
4. **Pydantic schemas** — `CallFacts`, `ScoreResult`, `ExtractionMetadata`
5. **Scoring rubric** — pure function + unit tests (no LLM, can run in CI)
6. **Mock voice provider + mock transcripts** — full pipeline works end-to-end without Vapi
7. **Claude extractor** — Sonnet strict-tool-use, test against mock transcripts
8. **FastAPI webhook receiver** — one route, idempotent, validates Vapi signature
9. **Vapi provider** — real outbound call, then capture 5-6 real transcripts → `samples/`
10. **Switch to `RUN_MODE=replay`** — iterate extraction prompt cheaply
11. **Scheduler + business hours + retry logic**
12. **SDR one-liner generator** — Haiku
13. **`ranked.csv` export**

> **UI track (separate, later):** A frontend will be built against this backend after the pipeline is solid. Keep API endpoints clean and stably-shaped so the UI can plug in without backend rework.

## What's deliberately NOT in scope

- Real menu scraping (cuisine inference is "good enough" — document in README)
- Multi-tenancy / auth on the FastAPI app
- Production-grade observability (basic logging is fine)
- Concurrent call rate limiting (sequential is fine for 2,355 leads over a few hours)
- A/B testing different shopper personas (mention as "with more time")

Every design decision should be defensible against one of these dimensions.
