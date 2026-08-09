# Contributing

## Development contract

Production is a pinned Docker image running under Compose on DigitalOcean.
Changes must therefore pass both Python tests and the deployment-shaped Compose
smoke test. Do not validate only with Django's development server.

1. Branch from the latest `main`.
2. Keep each pull request focused and link the issue or acceptance criterion it
   proves.
3. Run the local checks below.
4. Push the branch and open a pull request. Do not merge with red or pending
   required checks.
5. Merge through GitHub. Never copy source files directly to the Droplet.

## Local setup

Docker Desktop with Compose v2 is the supported production-shaped setup:

```bash
git clone https://github.com/ChaiWithJai/open-speaker-operations.git
cd open-speaker-operations
cp .env.local.example .env
docker compose --project-name speakerops-local up -d --build --wait
curl --fail http://127.0.0.1:8001/speakerops-demo/cfp
```

The local environment is deliberately non-production and binds web/mock ports
to loopback. The seed is deterministic. The speaker, reviewer, chair, and admin accounts use
the documented demo password `speakerops-demo` locally. Never reuse that
password in production.

For Python-only iteration, use Python 3.11 and the commands in README. Before
requesting review, run the authoritative checks:

```bash
ruff check pretalx_speakerops tests mock_accelevents
ruff format --check pretalx_speakerops tests mock_accelevents
DJANGO_SETTINGS_MODULE=pretalx.common.settings.test_settings pytest -q tests
bash -n scripts/ci-compose-smoke.sh scripts/deploy-digitalocean.sh
scripts/ci-compose-smoke.sh
```

## Pull-request expectations

- Add regression coverage for changed behavior and measurable performance
  budgets for performance work.
- Keep migrations backward-compatible with the previously deployed image when
  possible. Call out irreversible migrations explicitly in the PR and runbook.
- Do not commit `.env`, database dumps, credentials, SSH keys, screenshots, or
  generated runtime data.
- Use image SHA tags, not `latest`, in deployment evidence.
- Include the exact test commands and relevant live verification in the PR.
- Treat changes to Docker, workflows, migrations, authentication, uploads, and
  deployment scripts as production-sensitive review areas.

## Release flow

```text
pull request → required CI → merge to main → immutable GHCR image
             → protected production environment → backup → deploy → verify
```

PR workflows have read-only repository permissions and cannot deploy. Image
publication happens only after all `main` checks pass. The deployment job uses
GitHub Environment secrets and should require an environment reviewer for the
competition demo.

If deployment verification fails, the deployment script restores the previous
`APP_IMAGE` value and starts the previous image. Database restoration is a
separate, explicit operator action because automatically reversing migrations
can destroy data.

## Production access

Use the GitHub Actions deployment workflow for routine releases and rollbacks.
Direct SSH is reserved for diagnosis, restore drills, and incident recovery.
Every direct production action must be summarized in the related PR or issue.

See [docs/digitalocean.md](./docs/digitalocean.md) for the complete operator
runbook.
