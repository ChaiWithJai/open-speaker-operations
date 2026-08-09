# DigitalOcean demo runbook

The demo runs at `https://loop.dharmicdata.org` on the existing `writebook`
Droplet. Caddy owns TLS and proxies to the application on the loopback-only port
`127.0.0.1:8001`. The Compose project is isolated as `speakerops`, so unrelated
containers and host ports are not reused or stopped.

## Deploy

Routine deployments are performed by `.github/workflows/deploy-digitalocean.yml`,
not by building or copying application source on the Droplet. Configure a
protected GitHub Environment named `production` with a required reviewer.

Environment secrets:

- `DIGITALOCEAN_HOST`: Droplet hostname or IPv4 address.
- `DIGITALOCEAN_USER`: restricted deployment user (or `root` until one exists).
- `DIGITALOCEAN_SSH_KEY`: private key dedicated to this repository.
- `DIGITALOCEAN_SSH_KNOWN_HOSTS`: pinned `known_hosts` entry for the Droplet.

Optional environment variables:

- `DIGITALOCEAN_APP_DIR` (default `/opt/open-speaker-operations`).
- `SPEAKEROPS_PUBLIC_URL` (default `https://loop.dharmicdata.org`).

On a green `main` build, CI publishes the commit-SHA image and the deployment
workflow uploads the versioned Compose/runbook contract, creates a database
backup, deploys, waits for health, and verifies the public landing page and CFP.

### First-time host setup

1. Create `/opt/open-speaker-operations/.env` with mode `0600` from the
   production-oriented `.env.example` (not `.env.local.example`).
   Use unique values for `POSTGRES_PASSWORD` and `DJANGO_SUPERUSER_PASSWORD`, and
   pin `APP_IMAGE` to an immutable commit SHA.
2. Copy `docker-compose.yml` to `/opt/open-speaker-operations/docker-compose.yml`.
3. Authenticate Docker to GHCR, then run:

   ```sh
   cd /opt/open-speaker-operations
   docker compose --project-name speakerops pull
   docker compose --project-name speakerops up -d --wait
   ```

4. Add this site to the host Caddyfile, validate it, then reload Caddy:

   ```caddyfile
   loop.dharmicdata.org {
       reverse_proxy 127.0.0.1:8001
   }
   ```

The DNS record is an `A` record for `loop.dharmicdata.org` pointing to the
Droplet's public IPv4 address. Caddy obtains and renews the certificate after DNS
resolves.

### Manual redeploy or image rollback

Use **Actions → Deploy DigitalOcean → Run workflow** and provide a full
40-character commit SHA whose image exists in GHCR. This exercises the same
backup, health, and rollback logic as an automatic deployment. Do not use
`latest`.

## Verify

```sh
docker compose --project-name speakerops ps
curl --fail --silent --show-error https://loop.dharmicdata.org/ >/dev/null
curl --fail --silent --show-error https://loop.dharmicdata.org/speakerops-demo/cfp >/dev/null
```

Also exercise the speaker, reviewer, chair, agenda, and synchronization journeys
in a real browser and confirm that no first-party static assets fail.

## Measured demo sizing

The 2-vCPU/4-GB demo Droplet uses two Gunicorn workers with three threads each
and one Celery worker process. This provides six HTTP request slots without the
CPU contention observed with three Gunicorn processes.

On the deterministic seed, commit `a58c2f0520f8b03f1fa7336593020dbee3624013`
produced these warm Django query counts: dashboard 17, task drilldown 19, agenda
13, reviewer 14, and sync console 15. Query-budget tests enforce fewer than 40
queries for the chair views and a maximum of 30 for a reviewer screen with 11
criteria.

The production dashboard reuses only its event-level count/status snapshot for
two seconds. Authentication, permissions, messages, CSRF state, and HTML remain
per-request. From a separate machine, five persistent HTTPS clients with five
independent authenticated sessions made three 300-request runs. Their aggregate
p50 response-start values were 188.3, 185.4, and 204.7 ms; p95 values were 355.0,
370.6, and 415.5 ms. All 900 responses were HTTP 200.

During the resource-sampled run, the web container peaked at 7.56% of the
3.824-GiB host limit, PostgreSQL at 1.88%, and the Celery worker at 3.21%. Host
swap use remained zero. The web container peaked at 91.85% CPU, leaving the
second vCPU available for the database, proxy, and worker.

The PostgreSQL hot-path plans completed in 0.05–0.14 ms on demo-shaped data.
Existing event and foreign-key indexes covered selective lookups, while the small
proposal and schedule tables were cheaper to scan. No speculative indexes were
added.

## Back up and restore

Create a database backup before upgrades:

```sh
cd /opt/open-speaker-operations
umask 077
docker compose --project-name speakerops exec -T postgres \
  pg_dump -U speakerops -d speakerops -Fc > speakerops.dump
```

Restore into a stopped web/worker pair after confirming the target database:

```sh
cd /opt/open-speaker-operations
docker compose --project-name speakerops stop web worker
docker compose --project-name speakerops exec -T postgres \
  pg_restore -U speakerops -d speakerops --clean --if-exists < speakerops.dump
docker compose --project-name speakerops up -d --wait
```

The `pretalx-data` volume contains uploaded media and generated assets and should
be copied with the database backup for a durable environment.

## Roll back

Prefer the manual GitHub workflow with the previous verified commit SHA. If
GitHub Actions is unavailable, set `APP_IMAGE` in `.env` to that SHA and run
`pull` followed by `up -d --wait`. Compose retains the database and data volume.
Do not remove volumes during rollback.

The deployment script automatically restores the previous image setting when
container or public-URL verification fails. It does not automatically restore a
database because reversing migrations without an operator decision can destroy
data. Use the timestamped pre-deploy dump and the restore procedure above when
the incident requires data rollback.
