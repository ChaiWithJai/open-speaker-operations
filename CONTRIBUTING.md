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

### macOS workspace and cache placement

Keep active checkouts, virtual environments, browser runtimes, and evaluator
artifacts outside iCloud Drive, Desktop, and Documents. File Provider can leave
large dependency trees as `dataless` placeholders, which makes ordinary Git,
Python, and browser operations repeatedly hydrate files and appear to hang.
The supported macOS layout is:

```text
$HOME/Developer/speakerops-workspace/       active repositories and worktrees
$HOME/.config/speakerops/                   private local environment files
$HOME/Library/Caches/speakerops/            disposable package/browser caches
```

Create those directories with private defaults and point disposable caches at
the non-cloud location:

```bash
mkdir -p "$HOME/Developer/speakerops-workspace" \
  "$HOME/.config/speakerops" \
  "$HOME/Library/Caches/speakerops/uv" \
  "$HOME/Library/Caches/speakerops/playwright"
chmod 700 "$HOME/.config/speakerops"
export UV_CACHE_DIR="$HOME/Library/Caches/speakerops/uv"
export PLAYWRIGHT_BROWSERS_PATH="$HOME/Library/Caches/speakerops/playwright"
```

Store local values in `$HOME/.config/speakerops/local.env`, set it to mode
`600`, and pass it explicitly with Compose's `--env-file` option. Never copy a
production credential into a repository, shell transcript, issue, screenshot,
or benchmark artifact. A checkout-local `.venv` is acceptable when the checkout
itself is under `$HOME/Developer/speakerops-workspace`.

On macOS, run the metadata-only developer doctor before a long test or browser
run:

```bash
make doctor
# Or inspect multiple roots without reading or hydrating file contents:
python3 tools/developer_doctor.py \
  "$HOME/Developer/speakerops-workspace" \
  "$HOME/Library/Caches/speakerops"
```

Exit `0` means the tree is hydrated (or the host is not macOS), `1` means
`dataless` placeholders were found, and `2` means metadata could not be read.
The command never repairs or deletes anything. Move or rehydrate deliberately,
then rerun it; do not use a blanket Docker or workspace prune.

Docker Desktop with Compose v2 is the supported production-shaped setup:

```bash
cd "$HOME/Developer/speakerops-workspace"
git clone https://github.com/ChaiWithJai/open-speaker-operations.git
cd open-speaker-operations
cp .env.local.example "$HOME/.config/speakerops/local.env"
chmod 600 "$HOME/.config/speakerops/local.env"
docker compose --env-file "$HOME/.config/speakerops/local.env" \
  --project-name speakerops-local up -d --build --wait
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
- `uv run ruff format --check` — formatting
- `uv run ruff check` — linting
- `uv run python tools/check_repository_contract.py` — repository layout and generated-artifact policy
- `DJANGO_SETTINGS_MODULE=pretalx.common.settings.test_settings uv run pytest -q tests` — functional and query-budget tests
- `uv run python tools/check_context_graph.py` — requirement coverage gate
- syntax checks for JavaScript, Python operations tooling, and recovery shell scripts
- `tools/ci-compose-smoke.sh` — clean-volume production-shaped Docker smoke

CI invokes the same `make check`. Use `make check-python` while iterating when a Docker rebuild is not relevant; it is a subset, not the release gate.

## Architecture

Pretalx plugin (`pretalx_speakerops`) extending unmodified `pretalx==2025.2.2`:

- **Views** own authorization and HTTP handling
- **Services** (`onboarding/services.py`, `integrations/`) own business workflows
- **Models** own persistence and invariants
- **Receivers** observe pretalx signals and defer side effects via `transaction.on_commit`

Read [the architecture map](./docs/architecture.md) before adding a new
workflow. Follow `view → service/domain → model or integration → audit/outbox`.
New capabilities belong in named modules; do not add another unrelated concern
to `views.py` or `models.py`. GET requests never perform configuration or
workflow writes.

The [repository map](./docs/repository-map.md) is the placement authority:
deployment/recovery assets live in `deploy/`, contributor-only commands in
`tools/`, and tests use behavior/capability names rather than milestone names.

## Migrations

1. Change models and generate the migration with Pretalx's Django environment.
2. Inspect the migration; never accept an accidental field drop or rename.
3. Prefer additive schema changes. A destructive/data migration needs an ADR,
   an explicit reverse/recovery plan, and backup/restore evidence.
4. Run `python -m pretalx makemigrations --check --dry-run`, the full test suite,
   and the clean-volume Compose smoke.
5. Do not edit an already deployed migration; add the next numbered migration.

## Repository conventions

- Do not commit generated state (`.pytest_cache/`, `.ruff_cache/`, `.venv/`, `__pycache__/`, `*.egg-info/`, screenshots, profiling output, database dumps)
- Do not commit browser state/traces, coverage/build directories, local SQLite files, or backup snapshots; `make repository-contract` enforces tracked-path policy
- GET requests must not perform configuration writes
- Every implementation-critical claim needs a pinned upstream source and tests
- `docs/decisions/` records *why* seams were chosen; `docs/log/` records dead ends and corrections

## PR expectations

- Behavior-preserving unless the PR description argues otherwise
- New surfaces have tests; fixes regressions first
- Name the affected capability, migration/recovery impact, authorization boundary, and acceptance evidence in the PR description
- Include browser/performance evidence when the changed surface can affect rendering or request cost
- Never commit secrets, local evidence artifacts, or generated screenshots to make a check pass
- `make check` passes locally before pushing
