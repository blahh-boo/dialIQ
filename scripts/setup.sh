#!/usr/bin/env bash
# One-time provisioning for Mystery Shop.
#
# SQLite by default → zero infra: no server to start, no database to create.
# `init-db` creates the schema (and the .db file) from the ORM models.
# Safe to re-run: every step is idempotent.
set -euo pipefail

# Always operate from the repo root regardless of where this is invoked.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

say() { printf '\n\033[1;34m▸ %s\033[0m\n' "$1"; }
ok()  { printf '  \033[1;32m✓\033[0m %s\n' "$1"; }

# ── 1. Create schema from the ORM models (idempotent — no Alembic) ──────────
say "Creating schema"
uv run mystery-shop init-db
ok "Schema present"

# ── 2. Final gate: doctor must pass (exits non-zero on any problem) ─────────
say "Running health check"
uv run mystery-shop doctor

printf '\n\033[1;32mSetup complete.\033[0m Next:  make seed\n'
