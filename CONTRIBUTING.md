# Contributing to Open Speaker Operations

## Quick start

```bash
git clone https://github.com/ChaiWithJai/open-speaker-operations.git
cd open-speaker-operations
cp .env.example .env
docker compose up --build
```

Visit `http://127.0.0.1:8001/`. Demo accounts (password `speakerops-demo`):
`chair@example.org`, `reviewer@example.org`, `speaker@example.org`.

## Local development (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export PRETALX_CONFIG_FILE="$PWD/docker/pretalx-local.cfg"
python -m pretalx migrate
python -m pretalx speakerops_seed
python -m pretalx runserver 127.0.0.1:8000 --noreload
```

## Validation

```bash
make check
```

This runs:
- `ruff format --check` — formatting
- `ruff check` — linting
- `pytest -q tests` — functional tests
- `python scripts/check_context_graph.py` — requirement coverage gate

CI invokes the same `make check`.

## Architecture

Pretalx plugin (`pretalx_speakerops`) extending unmodified `pretalx==2025.2.2`:

- **Views** own authorization and HTTP handling
- **Services** (`onboarding/services.py`, `integrations/`) own business workflows
- **Models** own persistence and invariants
- **Receivers** observe pretalx signals and defer side effects via `transaction.on_commit`

## Repository conventions

- Do not commit generated state (`.pytest_cache/`, `.ruff_cache/`, `.venv/`, `__pycache__/`, `*.egg-info/`, screenshots, profiling output, database dumps)
- GET requests must not perform configuration writes
- Every implementation-critical claim needs a pinned upstream source and tests
- `docs/decisions/` records *why* seams were chosen; `docs/log/` records dead ends and corrections

## PR expectations

- Behavior-preserving unless the PR description argues otherwise
- New surfaces have tests; fixes regressions first
- `make check` passes locally before pushing
