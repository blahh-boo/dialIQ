# Mystery Shop — operator entrypoints.
# Thin wrappers; all defensive logic lives in scripts/ and the CLI so the
# steps stay individually runnable and inspectable.

.DEFAULT_GOAL := help
.PHONY: help setup seed reset api ui call campaign-live mock

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1;36m%-8s\033[0m %s\n", $$1, $$2}'

setup:  ## One-time: create schema (SQLite by default) + health-check
	@bash scripts/setup.sh

seed:  ## Deterministic demo data (ingest → reset → campaign). Re-run-safe.
	@bash scripts/seed.sh

reset:  ## Wipe call data only (interactive confirm); leaves leads intact
	@uv run mystery-shop reset

api:  ## Run the backend (terminal 1)
	@uv run uvicorn maple.web.app:app --reload

ui:  ## Run the frontend (terminal 2)
	@npm --prefix frontend run dev

# ── Calling ──────────────────────────────────────────────────────────────────
# Three modes depending on what you need. See README § Run modes for details.

call:  ## Call ONE number live. Usage: make call NUMBER=+1XXXXXXXXXX
	# Use when: testing your live path or capturing a real transcript fixture
	# before running a full campaign. Polls until the call ends — no ngrok needed.
	# Saves a reusable transcript to samples/transcripts/real_call.json.
	@test -n "$(NUMBER)" || (echo "Error: NUMBER is required. Usage: make call NUMBER=+1XXXXXXXXXX" && exit 1)
	@RUN_MODE=live uv run mystery-shop call \
	  --to "$(NUMBER)" \
	  --save-fixture samples/transcripts/real_call.json

campaign-live:  ## Run a live campaign against the real lead list. Usage: make campaign-live LIMIT=20
	# Use when: running the actual mystery-shop operation against real restaurants.
	# Respects business hours (11am–2pm local) and the no-answer retry cap.
	@test -n "$(LIMIT)" || (echo "Error: LIMIT is required. Usage: make campaign-live LIMIT=20" && exit 1)
	@RUN_MODE=live uv run mystery-shop campaign --limit "$(LIMIT)"

mock:  ## Run a mock campaign locally (no calls, no credits). Usage: make mock LIMIT=5
	# Use when: developing, testing pipeline changes, or demoing offline.
	# Uses canned transcripts from samples/transcripts/ — zero network, zero cost.
	# Safe to run anytime; --ignore-business-hours so it works at any hour.
	@uv run mystery-shop campaign \
	  --limit "$(or $(LIMIT),5)" \
	  --ignore-business-hours
