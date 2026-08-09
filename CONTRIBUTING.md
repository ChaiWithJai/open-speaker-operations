# Contributing to Open Speaker Operations

## Development contract

Production is a pinned Docker image running under Compose on DigitalOcean.
Changes must therefore pass both Python tests and the deployment-shaped Compose
smoke test. Do not validate only with Django's development server.

1. Branch from the latest `main`.
2. Keep each pull request focused and link the issue or acceptance criterion it proves.
3. Run the local checks below.
4. Push the branch and open a pull request. Do not merge with red or pending required checks.
5. Merge through GitHub. Never copy source files directly to the Droplet.

## Quick start (local, production-shaped)

Docker Desktop with Compose v2 is the supported production-shaped setup:

```bash
git clone https://github.com/ChaiWithJai/open-speaker-operations.git
cd open-speaker-operations
cp .env.local.example .env
docker compose --project-name speakerops-local up -d --build --wait
curl --fail http://127.0.0.1:8001/speakerops-demo/cfp
```

The local environment is deliberately non-production and binds web/mock ports to loopback.
The seed is deterministic. The speaker, reviewer, chair, and admin accounts use the
documented demo password `speakerops-demo` locally. **Never reuse that password in production.**

Visit `http://127.0.0.1:8001/`. Demo accounts (password `speakerops-demo`):
`chair@example.org`, `reviewer@example.org`, `speaker@example.org`.

## Local development (Python-only)

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
