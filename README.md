# Open Speaker Operations

## North star: win with a demoable journey

The goal is to win the competition by rapidly prototyping a fully working,
demoable speaker/program-management solution aligned to the original
competition documentation, then iterating until a judge can complete the seeded
journey. The process is part of the deliverable: decisions, failures, decay,
and recovery stay visible through git history, logs, tests, and the context
graph.

**Subordination rule:** demoable journey first. Anything not reachable in the
seeded judge journey does not count as complete, no matter how elegant the
architecture is. The protected path is:

```text
CFP → review → acceptance → onboarding → conflict-aware release
→ public output → synchronization proof
```

Open-source planning and implementation baseline for replacing the
speaker/program-management subset of Sessionboard described in the AIE “Kill
My SaaS” competition.

## Architecture

Extend pretalx as a disclosed, license-compliant modular monolith. Use Rails 8 only if competition rules prohibit derivative work. Deploy the application and worker to DigitalOcean with PostgreSQL as authority, Cloudflare R2 for objects, and Cloudflare at the edge.

## Documents

- [Product requirements](./kill-my-saas-prd.md)
- [Architecture RFC](./rails-monolith-rfc.md)
- [Implementation plan](./speaker-operations-implementation-plan.md)
- [Context graph](./docs/context-graph.md)
- [Working log](./docs/log/)
- [Auditable seam decisions](./docs/decisions/)
- [Contributing and production workflow](./CONTRIBUTING.md)
- [DigitalOcean deployment runbook](./docs/digitalocean.md)

## Run the seeded judge journey locally

The fastest clean-clone path uses Python 3.11, `uv`, a local virtualenv and
SQLite:

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
export PRETALX_CONFIG_FILE="$PWD/docker/pretalx-local.cfg"
.venv/bin/python -m pretalx migrate
.venv/bin/python -m pretalx speakerops_seed
.venv/bin/python -m pretalx runserver 127.0.0.1:8000 --noreload
```

Demo accounts all use password `speakerops-demo`:

```text
admin@example.org
chair@example.org
reviewer@example.org
speaker@example.org
```

Follow this numbered journey:

1. Open the seeded event `speakerops-demo` and the public CFP.
2. Open the proposal form, inspect the seven AIE field types, save a draft,
   resume it, and submit the proposal.
3. As the program chair, review proposals and inspect the two configured review rounds.
4. Accept the seeded proposal and open the speaker checklist.
5. Complete evidence-backed onboarding work; inspect overdue and waived tasks.
6. Open the organiser dashboard and inspect deliberate room/speaker conflicts.
7. Attempt release; the server blocks unresolved conflicts.
8. Resolve the conflicts and release the schedule.
9. Open the public schedule, ICS endpoint, and responsive embed.
10. Open the Accelevents sync card and inspect create/update/no-op items,
   failure state, and retry history.

### Docker stack

Docker Compose is the recommended contributor path because it matches the
production service topology. Copy the example environment, use an explicit
project name, and wait for health checks:

```bash
cp .env.local.example .env
docker compose --project-name speakerops-local up -d --build --wait
curl --fail http://127.0.0.1:8001/speakerops-demo/cfp
```

This starts Postgres, Redis, pretalx web, a Celery worker, and the standalone
mock Accelevents service. No cloud, AI, or Accelevents credentials are needed.
The mock is intentionally not production Accelevents: it implements only the
captured speaker/session contract, `Key` authentication, duplicate detection,
and deterministic failure injection for retry demonstrations.

Useful local commands:

```bash
docker compose --project-name speakerops-local ps
docker compose --project-name speakerops-local logs -f web worker
docker compose --project-name speakerops-local restart web
docker compose --project-name speakerops-local down
```

`down` preserves the named database/media volume. Use `down --volumes` only
when you intentionally want to erase local demo data. If ports `8001` or `9001`
are already occupied, set `WEB_BIND=127.0.0.1:18001` and
`MOCK_BIND=127.0.0.1:19001` in `.env`; do not stop unrelated projects.

## CI/CD in one minute

- Pull requests run the context-graph gate, Ruff, the full Python test suite,
  and a clean-volume Compose smoke test. They never deploy.
- A green push to `main` publishes one immutable image tagged with the commit
  SHA to GHCR.
- The `Deploy DigitalOcean` workflow deploys that SHA through the protected
  `production` GitHub Environment. It backs up PostgreSQL, updates the Compose
  definition, waits for health, checks the public URL, and rolls back the image
  setting if verification fails.
- A previous SHA can be redeployed from **Actions → Deploy DigitalOcean → Run
  workflow**. Production is never built from an uncommitted Droplet checkout.

See [CONTRIBUTING.md](./CONTRIBUTING.md) for required checks and
[docs/digitalocean.md](./docs/digitalocean.md) for secrets, first-time setup,
deployment, backup, restore, and rollback details.

## Requirements authority

The [canonical competition document](https://docs.google.com/document/d/1rBHJtiNKHv4i43tdf2Rm0sDEYuIcajhmAPoBKR_Az-A/mobilebasic) remains the source of truth for competition requirements. Repository issues provide traceability from those requirements to product, architecture, and implementation decisions.

## Evidence policy

DeepWiki is used for architectural navigation. Every implementation-critical claim must be verified against the exact pinned upstream source and tests because DeepWiki may lag the current repository revision.

## License

AGPL-3.0. Any future pretalx-derived implementation must also preserve and satisfy the applicable upstream license, notices, attribution, and modification-identification requirements.
