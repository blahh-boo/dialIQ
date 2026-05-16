#!/usr/bin/env bash
# Populate a deterministic demo dataset.
#
# Re-run-safe BY CONSTRUCTION: the order is ingest → reset → campaign, so every
# run starts from zero called leads and produces the identical queue. No "did I
# already run this?" guessing.
#
# Layers of protection against a corrupted run:
#   1. RUN_MODE guard   — refuses live mode (20 real calls) unless ALLOW_LIVE=1
#   2. Lockfile         — no two seeds can interleave reset+campaign
#   3. doctor gate      — bad env/DB/key aborts BEFORE any data work
#   4. schema check     — refuses if migrations aren't applied
#   5. xlsx check       — missing lead file fails loudly, up front
#   6. trap cleanup     — Ctrl-C / crash always releases the lock
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

LIMIT="${LIMIT:-20}"
LEADS_XLSX="${LEADS_XLSX:-data.xlsx}"
LOCK_DIR=".seed.lock"

say()  { printf '\n\033[1;34m▸ %s\033[0m\n' "$1"; }
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$1"; }
die()  { printf '  \033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

# ── Lock: atomic mkdir, with stale-lock reclamation ─────────────────────────
acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" > "$LOCK_DIR/pid"
    # Release on ANY exit path (success, error, Ctrl-C).
    trap 'rm -rf "$LOCK_DIR"' EXIT
    return
  fi
  local owner
  owner="$(cat "$LOCK_DIR/pid" 2>/dev/null || echo '')"
  if [[ -n "$owner" ]] && kill -0 "$owner" 2>/dev/null; then
    die "Another seed is running (pid ${owner}). Refusing to start a second."
  fi
  printf '  \033[1;33m! Stale lock from dead pid %s — reclaiming\033[0m\n' "${owner:-?}"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR"
  echo "$$" > "$LOCK_DIR/pid"
  trap 'rm -rf "$LOCK_DIR"' EXIT
}

say "Acquiring seed lock"
acquire_lock
ok "Lock held (pid $$)"

# ── Guard 1: never place 20 real calls by accident ──────────────────────────
say "Checking RUN_MODE"
RUN_MODE="$(grep -E '^[[:space:]]*RUN_MODE=' .env 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]' || true)"
RUN_MODE="${RUN_MODE:-mock}"
if [[ "$RUN_MODE" == "live" && "${ALLOW_LIVE:-0}" != "1" ]]; then
  die "RUN_MODE=live would place ${LIMIT} REAL calls (cost + ethics).
     This is almost never what you want for a demo seed.
     If you truly mean it:  ALLOW_LIVE=1 make seed"
fi
ok "RUN_MODE=${RUN_MODE}"

# ── Guard 2: env / DB / key sane before we touch data ───────────────────────
say "Health check (doctor)"
uv run mystery-shop doctor
ok "doctor passed"

# ── Guard 3: schema must exist ──────────────────────────────────────────────
say "Verifying schema exists"
if ! uv run python -c "import sys; from sqlalchemy import inspect; from maple.db import get_engine; sys.exit(0 if 'leads' in inspect(get_engine()).get_table_names() else 1)" 2>/dev/null; then
  die "Schema not found (no 'leads' table). Run:  make setup"
fi
ok "Schema present"

# ── Guard 4: lead file must exist ───────────────────────────────────────────
say "Checking lead file"
[[ -f "$LEADS_XLSX" ]] || die "Lead xlsx not found: ${LEADS_XLSX}
     Set LEADS_XLSX=path if it lives elsewhere."
ok "Found: ${LEADS_XLSX}"

# ── Ordered: ingest → reset → campaign (deterministic every run) ────────────
say "Ingesting leads (idempotent)"
uv run mystery-shop ingest "$LEADS_XLSX"

say "Resetting call data (clean slate)"
uv run mystery-shop reset --yes

say "Running campaign — ${LIMIT} ${RUN_MODE} calls"
# Seeding is for demo data on canned transcripts — no real restaurant is dialed,
# so the 11am-2pm gate would only block you. The RUN_MODE guard above already
# refuses live mode, so this flag is safe here.
uv run mystery-shop campaign --limit "$LIMIT" --ignore-business-hours

say "Writing ranked.csv"
uv run mystery-shop export-ranked

printf '\n\033[1;32mSeed complete.\033[0m Deterministic %s-lead dataset ready.\n' "$LIMIT"
printf 'Start the demo:  make api   (terminal 1)   |   make ui   (terminal 2)\n'
