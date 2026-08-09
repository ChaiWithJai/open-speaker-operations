.PHONY: check format lint test context-graph migrate seed run

check: format lint test context-graph

format:
	ruff format pretalx_speakerops tests mock_accelevents

lint:
	ruff check pretalx_speakerops tests mock_accelevents

test:
	DJANGO_SETTINGS_MODULE=pretalx.common.settings.test_settings pytest -q tests

context-graph:
	python scripts/check_context_graph.py

migrate:
	python -m pretalx migrate

seed:
	python -m pretalx speakerops_seed

run:
	python -m pretalx runserver 127.0.0.1:8000 --noreload
