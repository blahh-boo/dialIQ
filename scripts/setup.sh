#!/usr/bin/env bash
# One-time machine provisioning for Mystery Shop.
#
# Safe to re-run: every step is guarded so a second run is a no-op, not an error.
# Does NOT start Postgres for you — starting a background system service as a
# side effect is surprising and hard to undo. It checks and tells you instead.
set -euo pipefail

# Always operate from the repo root regardless of where this is invoked.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

DB_NAME="${DB_NAME:-mysteryshop}"
PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"

say()  { printf '\n\033[1;34m▸ %s\033[0m\n' "$1"; }
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$1"; }
die()  { printf '  \033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

# ── 1. Postgres must be reachable BEFORE we mutate anything ──────────────────
say "Checking Postgres is running"
if command -v pg_isready >/dev/null 2>&1; then
  if ! pg_isready -h "$PG_HOST" -p "$PG_PORT" -q; then
    die "Postgres not reachable at ${PG_HOST}:${PG_PORT}.
     Start it first, e.g.:  brew services start postgresql@15
     (then re-run: make setup)"
  fi
  ok "Postgres is accepting connections"
else
  printf '  \033[1;33m! pg_isready not found — skipping liveness check\033[0m\n'
fi

# ── 2. Create the database (guarded — "already exists" is success) ──────────
say "Ensuring database '${DB_NAME}' exists"
if psql -h "$PG_HOST" -p "$PG_PORT" -lqt 2>/dev/null | cut -d '|' -f1 | grep -qw "$DB_NAME"; then
  ok "Database already exists — leaving it alone"
else
  createdb -h "$PG_HOST" -p "$PG_PORT" "$DB_NAME" \
    && ok "Created database '${DB_NAME}'" \
    || die "createdb failed for '${DB_NAME}'"
fi

# ── 3. Apply migrations (alembic upgrade is a no-op when already at head) ────
say "Applying migrations"
uv run alembic upgrade head
ok "Schema at head"

# ── 4. Final gate: doctor must pass (exits non-zero on any problem) ─────────
say "Running health check"
uv run mystery-shop doctor

printf '\n\033[1;32mSetup complete.\033[0m Next:  make seed\n'
