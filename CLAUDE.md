# Mystery Shopping System — Project Context

## What this is

A  AI phone-answering service for restaurants. This system mystery-shops prospective restaurant leads by placing automated phone calls, simulating a customer trying to place a takeout order, and producing **structured, SDR-actionable data** about each restaurant's phone experience.

Output for each call: structured data (not transcript dumps), including a non-negotiable `pickup: bool`, a 0-100 numeric score, a HOT/WARM/COLD tier, and a one-line SDR read.

## Hard constraints

- **Local-first.** Postgres on localhost. FastAPI on localhost. ngrok tunnel for Vapi webhooks. No Docker.
- **Anthropic API for all LLM work.** No OpenAI, no other providers in the pipeline.
- **Extraction must be separate from scoring.** LLM produces observations; pure-Python scores them.
- **`pickup: bool` is the load-bearing field.** Every other rubric dimension is downstream of it.
- **Bail-before-commit.** The agent must never finalize an order. Hard requirement for restaurant ethics.
- **UI is a key part of the final deliverable**, but is being designed/built separately and will land later. For now, build the backend with a clean API surface that a frontend can hang off (well-typed endpoints, stable response shapes, no logic trapped in CLI commands). Do not scaffold UI code in this repo yet — wait for the frontend spec.

## Tech stack

| Layer | Choice | Version pin |
|---|---|---|
| Language | Python | 3.11+ |
| Web framework | FastAPI | latest |
| Database | Postgres (local) | 15+ |
| ORM | SQLAlchemy | 2.0.49 |
| Migrations | Alembic | 1.18.4 |
| Voice | Vapi (vapi-server-sdk) | 1.9.0 |
| LLM | Anthropic SDK (`anthropic`) | 0.102.0 |
| Validation | Pydantic | 2.x |
| Data ingest | pandas + openpyxl | latest |
| Tunneling | ngrok (static domain) | — |
| Timezone | pgeocode + timezonefinder | 0.5.0 / 8.2.4 |

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
Postgres: leads table
   ↓ (scheduler picks eligible leads by tz + business hours)
Pre-call: Haiku infers cuisine_type + order_item from name/website
   ↓
Vapi POST /call with assistantOverrides.variableValues
   ↓
[Restaurant answers]
   ↓
Vapi end-of-call-report webhook → FastAPI /vapi/webhook
   ↓
Postgres: call_attempts + transcripts tables
   ↓
Background task: extraction pipeline
   ├─ Haiku Pass 1: answered_by classifier (HUMAN/VOICEMAIL/IVR/...)
   ├─ Sonnet Pass 2: 15-field strict-tool-use CallFacts extraction
   └─ Deterministic Python scorer → score + tier
   ↓
Haiku: generates SDR one-liner from facts + score
   ↓
Postgres: extractions + scores tables
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
mystery_shop/
├── CLAUDE.md                       # this file
├── README.md                       # for the reviewer
├── .env.example
├── alembic.ini
├── migrations/                     # alembic
├── pyproject.toml
├── samples/                        # real call outputs
│   ├── transcripts/
│   ├── extractions/
│   ├── sdr_one_liners/
│   ├── ranked.csv
│   └── cost_log.json
└── src/mystery_shop/
    ├── __init__.py
    ├── cli.py                      # python -m mystery_shop {call,ingest,score,doctor}
    ├── config.py                   # env vars, run mode
    ├── db/
    │   ├── models.py               # SQLAlchemy models
    │   └── session.py
    ├── ingest/
    │   ├── xlsx_loader.py          # pandas → leads table
    │   └── normalize.py            # phone E.164, tz inference
    ├── voice/
    │   ├── base.py                 # VoiceProvider Protocol
    │   ├── vapi_provider.py        # real Vapi
    │   ├── replay_provider.py      # transcripts from disk
    │   └── mock_provider.py        # canned
    ├── llm/
    │   ├── claude_client.py        # thin Anthropic SDK wrapper
    │   ├── precall.py              # cuisine_type + order_item gen
    │   ├── classifier.py           # Haiku answered_by pass
    │   ├── extractor.py            # Sonnet 15-field tool-use
    │   ├── summarizer.py           # Haiku one-liner
    │   ├── prompts/                # versioned .txt files
    │   └── schemas.py              # Pydantic CallFacts, etc.
    ├── scoring/
    │   ├── rubric.py               # score_call(facts) → ScoreResult
    │   └── tiers.py                # HOT/WARM/COLD thresholds
    ├── scheduling/
    │   ├── business_hours.py       # 11-2pm local, retry windows
    │   ├── interleave.py           # don't-call-twice-in-a-row
    │   └── worker.py               # picks eligible leads, fires calls
    ├── webhook/
    │   └── app.py                  # FastAPI; one route: POST /vapi/webhook
    └── export/
        └── ranked_csv.py           # final deliverable
```

## Database schema (5 tables)

- `leads` — restaurants from xlsx, with normalized phone, timezone, cuisine_type
- `call_attempts` — one row per dial attempt; status, vapi_call_id, ended_reason
- `transcripts` — raw_jsonb + plaintext + tsvector for FTS
- `extractions` — fields_jsonb (the 15 CallFacts) + model_used + prompt_version
- `scores` — pickup, numeric_score, tier, summary_one_liner

Full DDL in `migrations/versions/0001_initial.py`.

## The CallFacts schema (extraction output)

Defined as a Pydantic model in `src/mystery_shop/llm/schemas.py`. Non-boolean fields carry paired confidence + evidence in nested `ExtractionMetadata`. Strict tool use guarantees schema-valid output.

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

Pure function. Same `CallFacts` always produces the same `ScoreResult`. Rubric in `src/mystery_shop/scoring/rubric.py`. Score starts at 100, deductions subtracted, floored at 0. Bump `RUBRIC_VERSION` on any weight change.

Tier thresholds:
- **HOT:** `pickup == False` OR `call_abandoned_by_restaurant == True` OR `score ≤ 40`
- **WARM:** `41 ≤ score ≤ 70`
- **COLD:** `score ≥ 71`

Deduction table (v1):

| Signal | Condition | Points |
|---|---|---|
| `rings_to_answer` | unknown | -3 |
| | 3-4 rings | -5 |
| | 5+ rings | -10 |
| `put_on_hold` | True (base) | -5 |
| `hold_time_seconds` | 31-60s | -5 |
| | 61-120s | -12 |
| | 121s+ | -20 |
| `transfer_count` | 1 | -12 |
| | 2 | -20 |
| | 3+ | -30 |
| `call_abandoned_by_restaurant` | True | -30 + HOT override |
| `interruption_count` | 1-2 | -8 |
| | 3-4 | -15 |
| | 5+ | -20 |
| `repeated_information_count` | 1 | -10 |
| | 2 | -18 |
| | 3+ | -25 |
| `upsell_attempted` | False | -5 |
| `customer_effort_score` | 3 | -8 |
| | 4 | -15 |
| | 5 | -22 |

## Conventions

- **Prompts live in `src/mystery_shop/llm/prompts/`** as versioned files (e.g., `extractor_v3.txt`). Never inline prompt strings in Python. Store the filename in `extractions.prompt_version` for auditability.
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
brew install postgresql ngrok uv
uv sync && npm --prefix frontend install
cp .env.example .env                 # then put a real ANTHROPIC_API_KEY in .env
uv run pre-commit install

make setup     # check Postgres, create DB, migrate, doctor   (run once)
make seed      # deterministic demo data — re-run-safe         (run anytime)
make api       # backend  (terminal 1) → http://localhost:8000
make ui        # frontend (terminal 2) → http://localhost:5173
```

`make help` lists every target. **`make seed` is re-run-safe by construction**
(`ingest → reset → campaign`, so every run rebuilds the identical queue) and is
guarded against the corrupting mistakes: it refuses `RUN_MODE=live` unless
`ALLOW_LIVE=1`, holds a lockfile so two seeds can't interleave, gates on `doctor`
and an applied schema before writing data, and `reset` refuses `--yes` against a
non-local DB. Defensive logic lives in `scripts/setup.sh`, `scripts/seed.sh`, and
the `reset` CLI command — the Makefile is a thin, inspectable wrapper.

### Raw CLI (what the targets wrap — for debugging)

```bash
# one-time
createdb mysteryshop
uv run alembic upgrade head

# dev loop
ngrok http --domain=<your-static-domain> 8000          # terminal 1 (live mode only)
uv run uvicorn mystery_shop.webhook.app:app --reload   # terminal 2
uv run mystery-shop doctor                             # health check
uv run mystery-shop ingest "…Round 2.xlsx"             # load leads
uv run mystery-shop reset                              # wipe call data (keeps leads)
uv run mystery-shop campaign --limit 20                # fire calls
uv run mystery-shop export-ranked                      # write samples/ranked.csv

# quality gates
uv run ruff check && uv run ruff format --check
uv run mypy src
uv run pytest
```

## CLI commands

- `doctor` — verify env, DB, Anthropic auth, and (live mode) Vapi config
- `ingest <xlsx>` — load + normalize lead list
- `campaign --limit N` — fire N calls respecting business hours + interleave
- `reset [--yes]` — wipe call data (call_attempts → … → scores), keep leads; refuses `--yes` on a non-local DB
- `score --call-attempt-id N` — re-score an existing call (rubric iteration)
- `replay <transcript.json>` — run the extraction pipeline against a saved transcript (no DB write)
- `export-ranked` — write `ranked.csv` for SDR consumption

> The four `make` targets (`setup`, `seed`, `api`, `ui`) wrap these — see **Local setup commands**.

## Vapi configuration (in their dashboard, just information for your awarness)

Saved assistant `Takeout Order Caller` configured with:

- Model: `claude-haiku-4-5`, `maxTokens: 250`
- Voice: ElevenLabs `dN8hviqdNrAsEcL57yFj` via `eleven_turbo_v2_5`
- Transcriber: Deepgram `flux-general-en`
- `firstMessage`: includes recording-consent disclosure
- `maxDurationSeconds: 240`
- `silenceTimeoutSeconds: 30`
- `endCallPhrases: ["I'll call you right back", "thanks bye", "gotta go"]`
- `voicemailDetection.provider: "vapi"`, `backoffPlan.startAtSeconds: 3`
- `backgroundSound: "office"`
- `serverMessages: ["end-of-call-report", "status-update"]`
- `server.url`: ngrok static domain + `/vapi/webhook`

System prompt uses Liquid variables: `{{shopper_name}}`, `{{restaurant_name}}`, `{{cuisine_type}}`, `{{order_item}}`. These are injected per-call via `assistantOverrides.variableValues`.

## Build order (do this in this order)

1. **Repo scaffold + pyproject.toml + .env.example**
2. **DB models + first Alembic migration** — get `alembic upgrade head` clean
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
14. **README + Loom**

> **UI track (separate, later):** A frontend will be built against this backend after the pipeline is solid. Keep API endpoints clean and stably-shaped so the UI can plug in without backend rework.

## What's deliberately NOT in scope

- Real menu scraping (cuisine inference is "good enough" — document in README)
- Multi-tenancy / auth on the FastAPI app
- Production-grade observability (basic logging is fine)
- Concurrent call rate limiting (sequential is fine for 2,355 leads over a few hours)
- A/B testing different shopper personas (mention as "with more time")

## Open questions / things to confirm with reviewer

- Recording consent: verbal disclosure in `firstMessage` is the chosen approach. Some 2-party states may need more. Documented as a known limitation.
- Real-restaurant ethics: bail script handles food waste; max 1 call per number to avoid annoyance.
- Cost ceiling for the sample run: targeting <$20 in API spend total.

## Reviewer evaluation rubric (memorize this)

The take-home will be scored on:

1. **System design** — clean architecture, components separated (call placement, extraction, storage, scheduling)
2. **Call orchestration** — realistic agent, retry logic, timezone handling, edge cases (no-answer, voicemail, busy)
3. **Data extraction** — reliable transcript→fields, handles ambiguity, extraction separated from scoring
4. **Code quality** — readable, error handling, not over- or under-engineered, config separate from logic
5. **Pragmatism** — built what matters, mocked the right things, acknowledged what's missing
6. **README quality** — understandable without reading all code, tradeoffs articulated, cost estimate included

Every design decision should be defensible against one of these dimensions.
