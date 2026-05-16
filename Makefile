# Mystery Shop — operator entrypoints.
# Thin wrappers; all defensive logic lives in scripts/ and the CLI so the
# steps stay individually runnable and inspectable.

.DEFAULT_GOAL := help
.PHONY: help setup seed reset api ui

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1;36m%-8s\033[0m %s\n", $$1, $$2}'

setup:  ## One-time: check Postgres, create DB, migrate, health-check
	@bash scripts/setup.sh

seed:  ## Deterministic demo data (ingest → reset → campaign). Re-run-safe.
	@bash scripts/seed.sh

reset:  ## Wipe call data only (interactive confirm); leaves leads intact
	@uv run mystery-shop reset

api:  ## Run the backend (terminal 1)
	@uv run uvicorn maple.web.app:app --reload

ui:  ## Run the frontend (terminal 2)
	@npm --prefix frontend run dev
