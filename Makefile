# APIx — see CLAUDE.md for the definition of done.
#
# Targets marked "Phase N" are deliberate stubs. This session scaffolds contracts only;
# lint and test are fully wired and must genuinely pass.

SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
COMPOSE ?= docker compose
COVERAGE_MIN ?= 80

.PHONY: help install up down logs migrate seed load-dgca lint fmt typecheck test \
        test-integration openapi collect-once index-run seed-synthetic synthetic-curves clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Resolve and install the workspace into .venv
	$(UV) sync --all-packages

# ---------------------------------------------------------------- stack ----

# Datastores first, then the schema, then the services. The API must never come up
# against an unmigrated database.
up: ## docker compose up, migrate, seed reference data
	$(COMPOSE) up -d --wait postgres redis
	$(COMPOSE) run --rm migrate
	$(COMPOSE) up -d --wait
	@echo "APIx is up. API: http://localhost:8000/docs  Web: http://localhost:5173"

down: ## Tear the stack down (volumes kept)
	$(COMPOSE) down

logs: ## Tail all service logs
	$(COMPOSE) logs -f --tail=100

migrate: ## Run Alembic migrations against DATABASE_URL
	$(UV) run alembic upgrade head

seed: ## Load reference data (airports, carriers, routes, sources)
	$(UV) run python -m apix_scheduler.seed_reference

load-dgca: ## Load a DGCA monthly extract into basket.yaml. Usage: make load-dgca FILE=db/seeds/dgca/2026-07.csv MONTH=2026-07 TOTAL_PAX=13200000
	$(UV) run python -m apix_scheduler.dgca_loader $(FILE) --month $(MONTH) --total-domestic-pax $(TOTAL_PAX)

# ----------------------------------------------------------- quality ----

lint: ## ruff check + ruff format --check + mypy
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(MAKE) typecheck

fmt: ## Apply ruff formatting and autofixes
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck: ## mypy (strict on apix_core)
	$(UV) run mypy --config-file mypy.ini

test: ## Unit tests with coverage gate on apix_core
	$(UV) run pytest \
		--cov=apix_core \
		--cov-report=term-missing \
		--cov-report=xml \
		--cov-fail-under=$(COVERAGE_MIN)

test-integration: ## Tests that need a container runtime (Postgres, Redis)
	$(UV) run pytest -m integration

openapi: ## Write the OpenAPI 3.1 document the front end builds against
	$(UV) run python -m apix_api.openapi > docs/openapi.json
	@echo "wrote docs/openapi.json"

# ------------------------------------------------------------ pipeline ----

collect-once: ## Single collection run against fixtures. Usage: make collect-once ROUTE=DEL-BOM
	$(UV) run python -m apix_collector collect-once --route $(ROUTE)

index-run: ## Compute the index for a date. Usage: make index-run DATE=2026-09-01
	@echo "index-run DATE=$(DATE): not implemented — Phase 3 wires the index maths"

DAYS ?= 90

seed-synthetic: ## Generate the labelled synthetic dataset. Usage: make seed-synthetic DAYS=90
	$(UV) run python -m apix_core.testing.seed --days $(DAYS)

synthetic-curves: ## Plot the synthetic lead-time/seasonality curves to docs/synthetic/
	$(UV) run python docs/plot_synthetic_curves.py

clean: ## Remove build and test artefacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache coverage.xml .coverage htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
