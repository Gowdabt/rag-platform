.PHONY: up down logs test test-unit test-ftest test-ui test-all migrate api frontend lint bootstrap frontend-build start stop restart

COMPOSE = docker compose -f docker/docker-compose.yml
PYTEST = PYTHONPATH=backend RAG_CONFIG_DIR=configs backend/.venv/bin/pytest

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

# Foreground (two terminals). Prefer ./scripts/start.sh for both processes.
api:
	cd backend && RAG_CONFIG_DIR=../configs RAG_ENV=development .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev

start:
	bash scripts/start.sh

stop:
	bash scripts/stop.sh

restart:
	bash scripts/restart.sh

migrate:
	cd backend && RAG_CONFIG_DIR=../configs .venv/bin/alembic upgrade head

test-unit:
	$(PYTEST) tests/unit -q --tb=short -m unit

test-ftest:
	$(PYTEST) tests/security tests/integration -q --tb=short -m "ftest or integration"

test-ui:
	cd frontend && npm run test:ui

test:
	$(PYTEST) tests -q --tb=short

test-all: test test-ui

bootstrap:
	bash scripts/bootstrap-local.sh

lint:
	backend/.venv/bin/ruff check backend/app tests

frontend-build:
	cd frontend && npm run build
