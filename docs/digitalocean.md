# DigitalOcean demo runbook

The demo runs at `https://loop.dharmicdata.org` on the existing `writebook`
Droplet. Caddy owns TLS and proxies to the application on the loopback-only port
`127.0.0.1:8001`. The Compose project is isolated as `speakerops`, so unrelated
containers and host ports are not reused or stopped.

## Deploy

1. Create `/opt/open-speaker-operations/.env` with mode `0600` from `.env.example`.
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

## Verify

```sh
docker compose --project-name speakerops ps
curl --fail --silent --show-error https://loop.dharmicdata.org/ >/dev/null
curl --fail --silent --show-error https://loop.dharmicdata.org/speakerops-demo/cfp >/dev/null
```

Also exercise the speaker, reviewer, chair, agenda, and synchronization journeys
in a real browser and confirm that no first-party static assets fail.

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

Set `APP_IMAGE` in `.env` to the previously verified commit SHA and run `pull`
followed by `up -d --wait` again. Compose retains the database and data volume.
Do not remove volumes during rollback.
