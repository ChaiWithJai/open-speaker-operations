# Buzz bounded demo runbook

This directory is an isolated, temporary Buzz relay for ADR 014. It is not a
SpeakerOps service: its Compose project, network, volumes, credentials, and
lifecycle are all separate. SpeakerOps must remain usable while this entire
project is stopped.

## Preconditions

1. Copy `.env.example` to `.env`, populate every blank secret from the secret
   store, and keep `.env` out of version control. The example pins the audited
   Buzz image by OCI digest. Do not substitute `main` or another mutable tag.
2. Keep both auth and membership gates enabled. Set `RELAY_OWNER_PUBKEY` to
   the 64-hex public key controlled by the demo operator; never commit the key
   material or reuse a SpeakerOps credential.
3. Confirm Docker storage has at least 10 GiB free and utilization is below 80%
   before starting. On native Linux, Docker's root directory is a
   host path and can be checked directly:

   ```sh
   docker_root=$(docker info --format '{{.DockerRootDir}}')
   df -Pk "$docker_root"
   docker system df -v
   ```

   On Docker Desktop, `DockerRootDir` is inside the Linux VM and is not a
   valid macOS/Windows host path. Use `docker system df -v`, check the host
   filesystem that stores Docker Desktop data, and inspect the virtual-disk
   allocation in Desktop settings instead. Stop and reclaim unrelated data
   deliberately if either threshold fails; this runbook never prunes Docker
   globally.
4. Verify the host-side agent prerequisites. Compose does not install Buzz
   Desktop, OpenCode, or SpeakerOps:

   ```sh
   opencode --version
   opencode acp --help
   opencode models
   opencode debug config
   uv --version
   ```

   For the zero-paid rehearsal on the current demo machine, `opencode debug
   config` must resolve the local `llama-server/qwen3.5-2b` model at
   `http://127.0.0.1:8080/v1`. Do not add or use an Anthropic credential for
   this rehearsal. A pickup machine may use another explicitly approved local
   tool-capable model, but must prove it can call `speakerops-reads` before the
   Buzz channel run.

   Start the local deterministic SpeakerOps stack separately and confirm its
   configured origin is reachable before asking the agent to call a typed
   read. The event seed deliberately does not import the much larger Conference
   Memory catalog. Load and verify that contracted catalog before the #41 hero
   conversation; a zero-row memory response is a failed preflight, not a valid
   demo result:

   ```sh
   docker compose --project-name speakerops-hci exec -T web \
     python -m pretalx speakerops_history_coverage \
     /app/pretalx_speakerops/data/conferences \
     --contract /app/pretalx_speakerops/data/conference_history_contract.json \
     --strict
   docker compose --project-name speakerops-hci exec -T web \
     python -m pretalx speakerops_import_history \
     /app/pretalx_speakerops/data/conferences \
     --contract /app/pretalx_speakerops/data/conference_history_contract.json \
     --prune --confirm-prune --verify \
     --report /tmp/speakerops-history-verification.json
   docker compose --project-name speakerops-hci exec -T web \
     test -s /tmp/speakerops-history-verification.json
   ```

   The strict contract must report 13 series, 204 editions, 19,466 talks,
   21,419 credits, 21,355 source identities, and 14,068 provisional people,
   while preserving 1,067 missing formats and 6,077 missing tracks as unknown.

   Buzz starts OpenCode in `~/.buzz`, so every imported agent must set
   `OPENCODE_CONFIG` to the absolute checked-in `opencode.json` path,
   `SPEAKEROPS_REPO_ROOT` to the absolute checkout, and
   `SPEAKEROPS_COMPOSE_PROJECT` to the explicitly targeted project. The
   checked-in config uses a stdio-transparent Compose launcher so reads execute
   inside that project's `web` container against its PostgreSQL database; it
   never uses the checkout's unrelated SQLite file. It inherits a fail-closed principal,
   event, capability set, and optional self-service subject from each Buzz
   agent process; use explicit reviewed values, never wildcards. For the
   eight-workflow demo, import and configure the three least-privilege agent
   profiles in `docs/buzz-eight-workflow-demo.md`.

   With one profile's environment exported, this read-only preflight must pass
   before opening a channel:

   ```sh
   python3 tools/run_speakerops_mcp_bridge.py --check
   opencode mcp list
   ```

   Log into SpeakerOps once in three separate browser profiles before taking a
   database snapshot: `chair@example.org`, `speaker@example.org`, and
   `reviewer@example.org`, all with the deterministic local demo password.
   Confirm the chair can open an organizer `go/` destination, the speaker can
   open only their checklist/profile destinations, and the reviewer can open
   only their assigned-review destination. A speaker or reviewer request for an
   organizer destination, and a reviewer request for the native speaker list,
   must return a non-disclosing 403/404. Keep cookies and credentials out of
   screenshots and channel messages.

## Start and observe

Run from the repository root. The explicit project name is mandatory even
though the Compose file also declares it:

```sh
docker compose --project-name buzz-demo --env-file buzz-demo/.env \
  --file buzz-demo/compose.yml config --quiet
docker compose --project-name buzz-demo --env-file buzz-demo/.env \
  --file buzz-demo/compose.yml up --detach --wait
docker compose --project-name buzz-demo --env-file buzz-demo/.env \
  --file buzz-demo/compose.yml ps
docker stats --no-stream $(docker compose --project-name buzz-demo \
  --env-file buzz-demo/.env --file buzz-demo/compose.yml ps --quiet)
```

Only `127.0.0.1:${BUZZ_HTTP_PORT:-3100}` is published. Use a separately
approved reverse proxy or SSH tunnel for remote access; never widen the bind
in this file. During the demo, record host usage with `df -Pk` and
`docker system df -v`; stop if free space falls below 10 GiB or utilization
reaches 80%.

## Stop, teardown, and retention

A reversible stop keeps all four data volumes:

```sh
docker compose --project-name buzz-demo --env-file buzz-demo/.env \
  --file buzz-demo/compose.yml stop
```

At the approved teardown date, first export any evidence that the retention
policy permits. Then remove **only** the `buzz-demo` project and its named
volumes with this exact, destructive command:

```sh
docker compose --project-name buzz-demo --env-file buzz-demo/.env \
  --file buzz-demo/compose.yml down --volumes --remove-orphans
```

Finally revoke the relay/operator keys, delete the populated `.env` through
the host's approved secure process, remove demo-only DNS/reverse-proxy rules,
and verify `docker volume ls --filter label=com.buzz-demo.volume` is empty.
Never use `docker system prune`, never target another Compose project, and
never delete SpeakerOps containers, networks, volumes, keys, or DNS.
