.PHONY: check check-python docker-smoke format format-check lint test context-graph repository-contract syntax migrate seed run

check: check-python docker-smoke

check-python: format-check lint repository-contract test context-graph syntax

format:
	uv run ruff format pretalx_speakerops tests mock_accelevents deploy tools

format-check:
	uv run ruff format --check pretalx_speakerops tests mock_accelevents deploy tools

lint:
	uv run ruff check pretalx_speakerops tests mock_accelevents deploy tools

test:
	DJANGO_SETTINGS_MODULE=pretalx.common.settings.test_settings uv run pytest -q tests

context-graph:
	uv run python tools/check_context_graph.py

repository-contract:
	uv run python tools/check_repository_contract.py

syntax:
	bash -n tools/ci-compose-smoke.sh deploy/scripts/deploy-digitalocean.sh deploy/scripts/backup-nightly.sh deploy/scripts/verify-restore.sh deploy/scripts/drill-image-rollback.sh
	uv run python -m py_compile deploy/smoke_journey.py tools/check_context_graph.py tools/check_repository_contract.py
	node --check tools/rehearse-judge-journey.js

docker-smoke:
	tools/ci-compose-smoke.sh

migrate:
	uv run python -m pretalx migrate

seed:
	uv run python -m pretalx speakerops_seed

run:
	uv run python -m pretalx runserver 127.0.0.1:8000 --noreload
