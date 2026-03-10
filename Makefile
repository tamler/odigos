.PHONY: test audit build up down logs

test:
	.venv/bin/python -m pytest tests/ -x -q

audit:
	.venv/bin/pip-audit

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f odigos
