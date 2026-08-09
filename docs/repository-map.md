# Repository map and artifact policy

The root is reserved for project metadata and entry-point configuration:
`README.md`, `CONTRIBUTING.md`, license/build metadata, the Dockerfile, the
Makefile, environment examples, and the one canonical `docker-compose.yml`.

| Location | Owner and contents |
| --- | --- |
| `pretalx_speakerops/` | Installed Pretalx plugin package and packaged data/assets |
| `tests/` | Behavior-oriented Python tests and deterministic test fixtures |
| `mock_accelevents/` | Standalone mock of the captured Accelevents contract |
| `deploy/` | Production/recovery scripts, smoke client, and host service definitions |
| `tools/` | Contributor-only validation and browser-rehearsal commands |
| `docker/` | Image entrypoint and Pretalx runtime configuration |
| `docs/` | Active architecture/operations docs, ADRs, evidence, logs, and archive |

## Test ownership

Tests are named for behaviors, not milestones. Cross-capability journey tests
live in `test_acceptance_journey.py`; onboarding, schedule publication,
Accelevents synchronization, performance, and operations contracts each have a
named module. A new test belongs in the narrowest existing capability module;
create another capability-named module when no existing module is honest.

Browser artifacts are written outside the repository by default. The only
browser fixture committed to the repository is the deterministic, inert PDF in
`tests/fixtures/browser/`, which exercises upload validation and has no build
step.

## Generated and vendored material

Never commit local databases, dumps, backup snapshots, browser session state,
screenshots, traces, profiles, coverage reports, test/build output, editable
installs, virtual environments, caches, or secrets. `make repository-contract`
checks tracked paths against this policy.

Packaged conference-history JSON is source evidence, not generated build
output. Its provenance and update contract are documented in
`pretalx_speakerops/data/conferences/README.md` and enforced by coverage/import
tests. The schedule-editor bundle is reproducibly built from the pinned Pretalx
dependency in the Dockerfile and is not committed.

## Structural changes

Physical package moves and module splits are separate, behavior-preserving
changes. They must prove editable and wheel installs, imports from outside the
checkout, migrations, the full Python/query suite, browser rehearsal,
performance gates, and the clean-volume Compose smoke before removing old
paths.

