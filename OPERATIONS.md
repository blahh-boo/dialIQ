# Operations

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
