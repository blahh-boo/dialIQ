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

Five tables: `leads`, `call_attempts`, `transcripts`, `extractions`, `scores`. Models + schema bootstrap in [maple/db.py](maple/db.py) (no Alembic — `init_db()` builds it from the models).

## Quick start

**Four commands. That's the whole thing.**

```bash
# 0. one-time install + secrets (only the very first time)
brew install postgresql ngrok uv
uv sync && npm --prefix frontend install
cp .env.example .env          # then put your real ANTHROPIC_API_KEY in .env

# 1. provision the machine — checks Postgres, creates the DB, migrates, health-checks
make setup

# 2. load a deterministic demo dataset — safe to re-run
make seed

# 3. run the two servers (two terminals)
make api          # terminal 1 — backend  → http://localhost:8000
make ui           # terminal 2 — frontend → http://localhost:5173
```

Open **http://localhost:5173** — the SDR cockpit, populated with real extracted data.

Run `make help` anytime to see every target. To check what's live or inspect
the database, see the [Operations](#operations) section.

### Why it's safe to re-run

`make seed` is **deterministic by construction**: it runs `ingest → reset → campaign` in
that order, so every run wipes prior call data and rebuilds the *identical* queue. You
can never accidentally double your dataset, and a half-finished or interrupted seed
fully recovers on the next `make seed`. Protections built into `make seed`:

- **Refuses `RUN_MODE=live`** (would place real calls) unless you explicitly opt in with `ALLOW_LIVE=1`
- **Lockfile** — two seeds can't run at once; interrupted seeds release the lock cleanly
- **`doctor` gate** — bad env / DB / API key aborts *before* any data is written
- **Schema check** — refuses to seed if the schema is missing (tells you to run `make setup`)
- **`reset` refuses `--yes` against a non-local database** — an automated seed can never truncate a remote/prod DB

### What each command does under the hood

| `make` target | Equivalent manual commands |
|---|---|
| `make setup`  | `pg_isready` → `createdb mysteryshop` → `uv run mystery-shop init-db` → `uv run mystery-shop doctor` |
| `make seed`   | `ingest data.xlsx` → `mystery-shop reset --yes` → `campaign --limit 20 --ignore-business-hours` → `export-ranked` |
| `make api`    | `uv run uvicorn maple.web.app:app --reload` |
| `make ui`     | `npm --prefix frontend run dev` |
| `make reset`  | `uv run mystery-shop reset` (interactive confirm; wipes call data, keeps leads) |

Every step is still individually runnable via the CLI — the Makefile is a thin,
inspectable wrapper, not a black box.

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

Defined in [maple/llm/schemas.py](maple/llm/schemas.py). Strict tool use guarantees schema-valid output. Per-field confidence + evidence live in nested `ExtractionMetadata`.

**Scored** (fed into [maple/scoring.py](maple/scoring.py)):

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
maple/
├── cli.py            # typer subcommands (doctor, init-db, ingest, campaign, ...)
├── config.py         # pydantic-settings, RUN_MODE validation
├── db.py             # 5 SQLAlchemy models + session_scope() + init_db() (no Alembic)
├── ingest.py         # phone E.164, zip zero-pad, tz + state norm, xlsx → leads
├── voice.py          # VoiceProvider Protocol + mock / replay / live Vapi providers
├── scoring.py        # pure rubric (same CallFacts → same ScoreResult) + tiers
├── scheduling.py     # business hours + interleave + campaign loop
├── export.py         # ranked.csv SDR deliverable
├── llm/
│   ├── client.py     # thin Anthropic wrapper with prompt caching
│   ├── schemas.py    # CallFacts, ScoreResult, ExtractionMetadata
│   ├── extractor.py  # Sonnet: 10 CallFacts via strict tool use (the heavy pass)
│   ├── passes.py     # the 3 short passes: precall, classifier, SDR one-liner
│   └── prompts/      # versioned .txt files (filename stored on each extraction row)
└── web/
    ├── app.py        # FastAPI: POST /vapi/webhook, GET /health, mounts /api
    ├── routes.py     # /api/* cockpit endpoints
    ├── pipeline.py   # webhook-path extraction pipeline
    └── models.py     # Vapi payload models + cockpit API response schemas
```

Schema changes: edit a model in `db.py`, then `dropdb mysteryshop && make setup`.
The DB is disposable and local — `make seed` rebuilds it deterministically.

## Operations
A quick reference for knowing the state of the system at any moment, and for
inspecting the database directly.

## Is each piece alive?

| Component | Check | Healthy output |
|---|---|---|
| **Postgres server** | `pg_isready -h localhost -p 5432` | `localhost:5432 - accepting connections` |
| **Database + schema + key** | `uv run mystery-shop doctor` | three `[OK]` lines |
| **Backend API** | `curl -s localhost:8000/health` | `{"status":"ok"}` |
| **Backend has data** | `curl -s localhost:8000/api/campaign/stats` | JSON with `mystery_shopped > 0` |
| **Frontend** | open `http://localhost:5173` | the cockpit renders |
| **Which run mode** | `grep '^RUN_MODE=' .env` | `mock` / `replay` / `live` |
| **Postgres background service** | `brew services list \| grep postgres` | `started` |

If `doctor` is green but the queue is empty, the DB is live but unseeded — run `make seed`.

## Inspecting the database

Open a SQL shell on the project DB:

```bash
psql mysteryshop
```

Useful `psql` meta-commands (inside the shell):

| Command | Shows |
|---|---|
| `\dt` | all tables |
| `\d leads` | the `leads` table's columns + indexes |
| `\d+ scores` | same, with extra detail |
| `\x` | toggle expanded (row-per-line) display — good for wide rows |
| `\q` | quit |

One-liners without entering the shell:

```bash
psql mysteryshop -c "SELECT count(*) FROM leads;"
psql mysteryshop -c "SELECT tier, count(*) FROM scores GROUP BY tier;"
```

## The 5 tables and what fills them

```
leads ──< call_attempts ──< extractions ──< scores
                   └──── transcripts (1:1 with call_attempts)
```

| Table | Filled by | "Is it populated?" query |
|---|---|---|
| `leads` | `make seed` → `ingest` | `SELECT count(*) FROM leads;` |
| `call_attempts` | `make seed` → `campaign` | `SELECT count(*) FROM call_attempts;` |
| `transcripts` | `campaign` (one per call) | `SELECT count(*) FROM transcripts;` |
| `extractions` | `campaign` (Claude 10-field extract) | `SELECT count(*) FROM extractions;` |
| `scores` | `campaign` (deterministic scorer) | `SELECT count(*) FROM scores;` |

A healthy seeded DB has: many `leads`, and `call_attempts = transcripts = extractions = scores = <campaign --limit N>`.

## Handy diagnostic queries

```sql
-- tier distribution (what the cockpit queue is grouped by)
SELECT tier, count(*), round(avg(numeric_score)) AS avg
FROM scores GROUP BY tier ORDER BY tier;

-- the SDR queue, exactly as the cockpit orders it (HOT first, worst first)
SELECT l.restaurant_name, s.tier, s.numeric_score, s.summary_one_liner
FROM scores s
JOIN extractions e ON e.id = s.extraction_id
JOIN call_attempts c ON c.id = e.call_attempt_id
JOIN leads l ON l.id = c.lead_id
ORDER BY array_position(ARRAY['HOT','WARM','COLD']::text[], s.tier::text),
         s.numeric_score ASC
LIMIT 20;

-- did any call not get picked up? (always HOT)
SELECT l.restaurant_name, e.answered_by, s.tier
FROM scores s
JOIN extractions e ON e.id = s.extraction_id
JOIN call_attempts c ON c.id = e.call_attempt_id
JOIN leads l ON l.id = c.lead_id
WHERE s.pickup = false;
```

## Resetting state

| Want | Command |
|---|---|
| Wipe call data, keep leads (interactive confirm) | `make reset` |
| Wipe + reload deterministic demo data | `make seed` (does reset → campaign internally) |
| Nuke the whole DB and start over | `dropdb mysteryshop && make setup && make seed` |

`make seed` is re-run-safe by construction — running it again always yields the
identical queue (it resets call data before re-running the campaign).

## Where the servers log

- **Backend** (`make api`): logs to the terminal it runs in. Extraction/scoring
  progress and the token-usage line print here.
- **Frontend** (`make ui`): Vite dev server output; build errors show in the
  browser console and that terminal.
- Nothing logs to a file by default (local-first, `LOG_LEVEL` in `.env`).
