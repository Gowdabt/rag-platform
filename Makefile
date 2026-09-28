.PHONY: up down logs test migrate api frontend lint bootstrap desktop desktop-dist frontend-build

COMPOSE = docker compose -f docker/docker-compose.yml

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

api:
	cd backend && RAG_CONFIG_DIR=../configs RAG_ENV=development .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

migrate:
	cd backend && RAG_CONFIG_DIR=../configs .venv/bin/alembic upgrade head

test:
	PYTHONPATH=backend RAG_CONFIG_DIR=configs backend/.venv/bin/pytest tests -q

bootstrap:
	bash scripts/bootstrap-local.sh

lint:
	backend/.venv/bin/ruff check backend/app tests

frontend-build:
	cd frontend && npm run build

desktop: frontend-build
	cd desktop && npm install
	cd desktop && npm start

desktop-dist: frontend-build
	cd desktop && npm install
	cd desktop && npm run dist
