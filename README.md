# Mystery Shop

Automated phone-based mystery shopping for restaurant leads. Places a takeout-order call via Vapi, extracts ten structured facts per call with Claude, scores each call deterministically, and outputs an SDR-ranked CSV.

The output for each restaurant is structured data — not a transcript dump — including a non-negotiable `pickup: bool`, a 0-100 numeric score, a HOT/WARM/COLD tier, and a one-line SDR brief.

## Services

| Service | What it does |
|---|---|
| **Lead ingest** | Reads an xlsx export, normalises phones to E.164, infers timezone from zip/state, deduplicates, and loads into `leads`. |
| **Campaign orchestrator** | Selects eligible leads (business hours, never-called or retryable no-answer), infers what to order per restaurant via Haiku, and dispatches calls through the voice provider. |
| **Extraction pipeline** | After each call: classifies who answered (Haiku), extracts 10 structured facts from the transcript (Sonnet strict tool use), and scores them deterministically (pure Python). |
| **SDR export** | Writes `ranked.csv` sorted HOT → WARM → COLD, worst score first — the one file an SDR needs. |
| **Cockpit API** | FastAPI endpoints the frontend reads; also receives and processes Vapi end-of-call webhooks. |

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
brew install ngrok uv          # no database server needed — SQLite is the default
uv sync && npm --prefix frontend install
cp .env.example .env          # then put your real ANTHROPIC_API_KEY in .env

# 1. create the schema and verify your setup (SQLite file created automatically)
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
| `make setup`  | `uv run mystery-shop init-db` → `uv run mystery-shop doctor` |
| `make seed`   | `ingest data.xlsx` → `mystery-shop reset --yes` → `campaign --limit 20 --ignore-business-hours` → `export-ranked` |
| `make api`    | `uv run uvicorn maple.web.app:app --reload` |
| `make ui`     | `npm --prefix frontend run dev` |
| `make reset`  | `uv run mystery-shop reset` (interactive confirm; wipes call data, keeps leads) |
| `make call NUMBER=+1XXX` | One live call via polling — no ngrok needed. Writes to DB + saves fixture. |
| `make campaign-live LIMIT=N` | Live campaign against real lead list. Webhook path — needs ngrok. |
| `make mock [LIMIT=5]` | Mock campaign locally — no calls, no credits. |

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
| `call --to <e164>`          | Place ONE real Vapi call (RUN_MODE=live), poll until it ends, run the full pipeline; `--save-fixture` to also capture the transcript |
| `export-ranked`             | Write `samples/ranked.csv` ranked by SDR priority                                                  |

## Webhook

`POST /vapi/webhook` — receives Vapi `end-of-call-report` and `status-update` events.

- Validates the `x-vapi-secret` header when `VAPI_WEBHOOK_SECRET` is set
- Returns 200 immediately; extraction runs in a `BackgroundTask`
- Idempotent: duplicate deliveries with the same `vapi_call_id` short-circuit on the partial unique index

## The 10 CallFacts (extraction shape)

Defined in [maple/llm/schemas.py](maple/llm/schemas.py). Sonnet's strict tool-use call guarantees schema-valid output on every extraction — no post-hoc parsing or fallback guessing. Each non-boolean field carries a nested `ExtractionMetadata` with a `confidence` float (0–1) and a verbatim `evidence` quote from the transcript, so every fact is auditable back to the words that produced it.

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

Pure Python — same `CallFacts` always produces the same `ScoreResult`. Score starts at 100, deductions subtracted, floored at 0. `RUBRIC_VERSION` is stamped on every score row; bump it on any weight change so every historical score is auditable to the exact rubric that produced it.

Tier thresholds: **HOT** = no pickup OR abandoned OR `score ≤ 40` · **WARM** = `41-70` · **COLD** = `≥ 71`

### Why these signals and not others

Every dimension is a **revenue-loss proxy** — a concrete reason a takeout caller would hang up or not order again. That's the product being sold: "your phone experience is costing you orders."

| Signal | Why it's here | Points |
|---|---|---|
| `pickup == False` | 100% lost order — the headline finding | → HOT, score 0 |
| `call_abandoned_by_restaurant` | They hung up on a customer mid-call | -30 → HOT override |
| `transfer_count` 1/2/3+ | Each transfer risks losing the caller; 3+ is a broken process | -12/-20/-30 |
| `put_on_hold` + `hold_time_seconds` | Any hold is friction; duration compounds it | -5 base, -5/-12/-20 |
| `repeated_information_count` | Customer had to repeat themselves — broken handoff | -10/-18/-25 |
| `interruption_count` | Caller was rushed or talked over | -8/-15/-20 |
| `customer_effort_score` (1–5) | Holistic felt difficulty; captures dead air and confusion the discrete counts miss | -8/-15/-22 |
| `rings_to_answer` | Pickup latency — slow answer loses impatient callers | -5/-10 (unknown = 0) |
| `upsell_attempted` | Positive signal — absence is normal, never a penalty | 0 |

**Why only friction signals?** Re-dialing a restaurant to evaluate politeness or friendliness is not the SDR's job. The rubric targets what causes order drop-off — that's directly actionable. Scoring "warmth" would add noise without changing what an SDR does in 5 seconds.

**On `customer_effort_score`:** This is an LLM-produced *observation* (how hard did the caller have to work?), not a score. The scorer's role is to weight it consistently. CES deliberately compounds with the discrete counts — a call that scores badly on both axes should bottom out, because the customer experience was genuinely bad on multiple dimensions. That compounding is intentional, not double-counting.

**`key_failure_quote`** is the one field that's purely observational (never scored). It's the verbatim line that best explains a low score — the SDR's cold-open: *"I called and your host said 'hold on' then the line went silent for two minutes."*

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
uv run mypy maple
uv run pytest
```

181 tests across 10 files. No network dependency — the LLM and voice providers are mocked. A DB-insert smoke test (`test_db_schema.py`) exercises the schema + FK chain on in-memory SQLite so dialect bugs fail in CI; the rest is pure-unit.

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

Schema changes: edit a model in `db.py`, then `rm -f maple.db && make setup`.
The DB is disposable and local — `make seed` rebuilds it deterministically.

## Operations
A quick reference for knowing the state of the system at any moment, and for
inspecting the database directly.

## Is each piece alive?

| Component | Check | Healthy output |
|---|---|---|
| **Database + schema + key** | `uv run mystery-shop doctor` | `[OK]` lines for env, database, anthropic key |
| **Backend API** | `curl -s localhost:8000/health` | `{"status":"ok"}` |
| **Backend has data** | `curl -s localhost:8000/api/campaign/stats` | JSON with `mystery_shopped > 0` |
| **Frontend** | open `http://localhost:5173` | the cockpit renders |
| **Which run mode** | `grep '^RUN_MODE=' .env` | `mock` / `replay` / `live` |
| **Which database** | `grep '^DATABASE_URL=' .env` | SQLite path or postgres DSN |

If `doctor` is green but the queue is empty, the DB is live but unseeded — run `make seed`.

## Inspecting the database

Open a SQL shell (SQLite default):

```bash
sqlite3 maple.db
```

Useful commands inside the shell:

| Command | Shows |
|---|---|
| `.tables` | all tables |
| `.schema leads` | the `leads` table's columns + indexes |
| `.mode column` + `.headers on` | readable column output |
| `.quit` | exit |

One-liners without entering the shell:

```bash
sqlite3 maple.db "SELECT count(*) FROM leads;"
sqlite3 maple.db "SELECT tier, count(*) FROM scores GROUP BY tier;"
```

If you've swapped to PostgreSQL (`DATABASE_URL=postgresql+psycopg://...`), replace `sqlite3 maple.db` with `psql <your-db-name>`.

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
ORDER BY CASE s.tier WHEN 'HOT' THEN 1 WHEN 'WARM' THEN 2 ELSE 3 END,
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
| Nuke the whole DB and start over | `rm -f maple.db && make setup && make seed` |

`make seed` is re-run-safe by construction — running it again always yields the
identical queue (it resets call data before re-running the campaign).

## Where the servers log

- **Backend** (`make api`): logs to the terminal it runs in. Extraction/scoring
  progress and the token-usage line print here.
- **Frontend** (`make ui`): Vite dev server output; build errors show in the
  browser console and that terminal.
- Nothing logs to a file by default (local-first, `LOG_LEVEL` in `.env`).
