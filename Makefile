.DEFAULT_GOAL := help
.PHONY: help install fmt lint type test test-all up down migrate ready probe check

help:  ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

install:  ## Install all dependency groups
	uv sync --all-groups

fmt:  ## Format
	uv run ruff format . && uv run ruff check --fix .

lint:  ## Lint (blocking in CI)
	uv run ruff check . && uv run ruff format --check .

type:  ## Type-check, strict, app/ only
	uv run mypy app

test:  ## Fast suite: no containers, no network
	uv run pytest -m "unit or api or security" -q

test-all:  ## Everything, including integration (needs the compose stack)
	uv run pytest -q

check: lint type test  ## What CI runs

up:  ## Start the stack (API :8010, pgvector :5435)
	docker compose up -d --build

down:  ## Stop the stack
	docker compose down

migrate:  ## Apply migrations
	uv run alembic upgrade head

ready:  ## Readiness report
	@curl -s localhost:8010/ready | python3 -m json.tool

probe:  ## Record model capabilities (writes eval/reports/)
	uv run python scripts/probe_model_capabilities.py
