# Speaker Operations operator handoff

This is the owner-facing recovery and credential-rotation contract for the
DigitalOcean demo. Repository automation is safe to review and exercise locally;
production installation and drills require the protected environment owner.

## Ownership and boundaries

- Production application directory: `/opt/open-speaker-operations`.
- Production Compose project: `speakerops`. Local verification in this repository
  uses only `speakerops-hci` with `WEB_BIND=127.0.0.1:38001`,
  `MOCK_BIND=127.0.0.1:39001`, and
  `PRETALX_SITE_URL=http://127.0.0.1:38001`.
- Never run `docker compose down` without an explicit project name. Never use
  `down --volumes` in production.
- Database and uploaded media are authoritative. An image rollback does not imply
  a database rollback.

## Protected smoke journey

The smoke runner logs in through the real CSRF-protected forms using separate
speaker, reviewer, and chair sessions. It verifies the speaker checklist,
reviewer queue, chair command center, authenticated sync console, public embed,
and gallery with a mobile user agent. It performs no application mutations.

```bash
read -rsp 'Smoke account password: ' SPEAKEROPS_SMOKE_PASSWORD; export SPEAKEROPS_SMOKE_PASSWORD
python3 deploy/smoke_journey.py --base-url http://127.0.0.1:38001
unset SPEAKEROPS_SMOKE_PASSWORD
```

Credentials are accepted only through the environment, never command-line
arguments or output. The deployment script reads the same secret from the
mode-`0600` host `.env` when an operator has not exported it.

## Nightly backups and retention

`deploy/scripts/backup-nightly.sh` creates one mode-restricted directory containing a
PostgreSQL custom-format dump, the `/data` media archive, checksums, and a
manifest. Retention only removes timestamped `speakerops-*` directories inside
the validated application backup root.

Dry-run locally without touching any container:

```bash
deploy/scripts/backup-nightly.sh --app-dir "$PWD" --project speakerops-hci --dry-run
```

Production owner installation:

1. Install `backup-nightly.sh` as `/opt/open-speaker-operations/backup-nightly.sh`.
2. Install the service and timer from `deploy/systemd/` in `/etc/systemd/system/`.
3. Copy `backup.env.example` to `/etc/speakerops/backup.env`, make it mode `0600`,
   and confirm retention policy with the owner.
4. Run `systemctl daemon-reload`, start one manual service run, inspect its
   manifest/checksums, then enable `speakerops-backup.timer`.
5. Verify `systemctl list-timers speakerops-backup.timer` and alert when the most
   recent successful backup is older than 26 hours.
6. Copy snapshots off-host to owner-approved encrypted storage. A same-Droplet
   backup is not disaster recovery.

The repository supplies the schedule and retention implementation; the timer is
not considered operational until the production owner installs it and records
one successful run plus retention evidence.

## Isolated restore verification

The restore script refuses to operate without `--yes`. It verifies checksums,
creates a uniquely named database and media volume, starts one loopback-only
temporary web container, runs the complete protected smoke journey, then removes
only those exact temporary resources. It never stops or recreates production
web, worker, PostgreSQL, Redis, or mock services.

```bash
deploy/scripts/verify-restore.sh \
  --app-dir "$PWD" \
  --project speakerops-hci \
  --backup "$PWD/backups/speakerops-YYYYMMDDTHHMMSSZ"

# After reviewing the dry-run and exporting the restored demo password:
SPEAKEROPS_SMOKE_PASSWORD='from-secure-prompt' deploy/scripts/verify-restore.sh \
  --app-dir "$PWD" --project speakerops-hci \
  --bind 127.0.0.1:48001 \
  --backup "$PWD/backups/speakerops-YYYYMMDDTHHMMSSZ" --yes
```

For production, replace `speakerops-hci` with the explicitly reviewed
`speakerops` project and run under the deployment owner. Retain the timestamp,
checksum output, six-surface smoke JSON, and cleanup confirmation as evidence.

## Previous-image rollback-and-return drill

The drill accepts only two full 40-character GHCR image tags. It requires the
declared current image to match `.env`, deploys and smokes the previous image,
then deploys and smokes current main. An exit trap returns to the declared
current image after every failure path.

Run without `--yes` first. The real invocation must be performed through the
protected production owner session during an announced window:

```bash
SPEAKEROPS_SMOKE_PASSWORD='from-secure-prompt' ./drill-image-rollback.sh \
  --app-dir /opt/open-speaker-operations \
  --current ghcr.io/chaiwithjai/open-speaker-operations:<current-40-sha> \
  --previous ghcr.io/chaiwithjai/open-speaker-operations:<previous-40-sha>
```

Add `--yes` only after confirming both image digests, the latest backup, active
host headroom, and the no-database-rollback decision. Record both smoke results
and final `.last-successful-image`.

The same mechanism can be rehearsed locally with two preloaded local image
objects using commit-shaped rehearsal tags. This proves switching and return
mechanics, not registry immutability. The no-pull switch is deliberately refused
unless the public URL is loopback-only and the Compose project begins with
`speakerops-hci`:

```bash
SPEAKEROPS_COMPOSE_PROJECT=speakerops-hci \
SPEAKEROPS_PUBLIC_URL=http://127.0.0.1:38001 \
SPEAKEROPS_SKIP_PULL=true \
SPEAKEROPS_SMOKE_PASSWORD='from-secure-prompt' \
  deploy/scripts/drill-image-rollback.sh \
    --app-dir /path/to/rehearsal-contract \
    --previous ghcr.io/chaiwithjai/open-speaker-operations:<previous-40-sha> \
    --current ghcr.io/chaiwithjai/open-speaker-operations:<current-40-sha> \
    --yes
```

Local success proves the deployment, smoke, exit-trap, and return mechanics for
the recorded local Docker image IDs. It does not substitute for pulling the
actual published RepoDigests and performing the announced drill under the
production owner.

## Credential rotation

Rotation order avoids losing the only working operator path:

1. Create and verify a second deployment SSH key; update
   `DIGITALOCEAN_SSH_KEY` and pinned `DIGITALOCEAN_SSH_KNOWN_HOSTS` in the
   protected GitHub Environment; run a read-only connection check; then revoke
   the prior key.
2. Rotate the GHCR read credential on the host, verify pulling a pinned digest,
   then revoke the old credential.
3. Set new, distinct `DJANGO_SUPERUSER_PASSWORD`,
   `SPEAKEROPS_DEMO_PASSWORD`, and `SPEAKEROPS_MOCK_KEY` values in the mode-`0600`
   host `.env`. Recreate only the `speakerops` services through the normal
   deployment. The deterministic seed reads these values; no password is printed.
4. For PostgreSQL, take and verify a backup first. Change the database role
   password in PostgreSQL and `.env` within one maintenance window, then recreate
   only web and worker and run the protected smoke. Keep the old value available
   in the approved secret manager until verification completes.
5. Rotate any real downstream Accelevents credential in its secret provider and
   update only its reference. The bundled mock key is not a production vendor
   credential.
6. Verify the six-surface smoke, synchronization preview (no external write),
   worker health, and a fresh nightly backup. Record date, owner, credential
   classes rotated, and evidence links—never secret values.

Break-glass access, environment reviewers, off-host backup destination, alert
routing, and the secret manager are owner decisions and must be named in the
private operations inventory before #27 closes.
