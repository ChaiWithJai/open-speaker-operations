import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL_SCRIPTS = (
    "tools/ci-compose-smoke.sh",
    "deploy/scripts/deploy-digitalocean.sh",
    "deploy/scripts/backup-nightly.sh",
    "deploy/scripts/verify-restore.sh",
    "deploy/scripts/drill-image-rollback.sh",
)


def test_recovery_shell_contracts_parse_and_backup_defaults_to_safe_project():
    subprocess.run(["bash", "-n", *(str(ROOT / path) for path in SHELL_SCRIPTS)], check=True)
    result = subprocess.run(
        [
            str(ROOT / "deploy/scripts/backup-nightly.sh"),
            "--app-dir",
            str(ROOT),
            "--project",
            "speakerops-hci",
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "DRY RUN project=speakerops-hci" in result.stdout
    assert "retention_days=14" in result.stdout


def test_smoke_parser_handles_minified_unquoted_csrf_and_covers_six_surfaces():
    path = ROOT / "deploy/smoke_journey.py"
    spec = importlib.util.spec_from_file_location("speakerops_smoke_journey", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert (
        module.csrf_token(
            "<form><input name=csrfmiddlewaretoken type=hidden value=token-123></form>"
        )
        == "token-123"
    )
    source = path.read_text()
    for fragment in (
        "speaker@example.org",
        "reviewer@example.org",
        "chair@example.org",
        '"sync"',
        '"embed"',
        '"mobile-gallery"',
    ):
        assert fragment in source


def test_nightly_timer_and_rotation_inputs_are_explicit():
    timer = (ROOT / "deploy/systemd/speakerops-backup.timer").read_text()
    service = (ROOT / "deploy/systemd/speakerops-backup.service").read_text()
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "OnCalendar=" in timer and "Persistent=true" in timer
    assert "backup-nightly.sh" in service and "--project speakerops" in service
    assert "SPEAKEROPS_DEMO_PASSWORD" in compose
    assert "SPEAKEROPS_MOCK_KEY" in compose


def test_no_pull_deploy_mode_is_restricted_to_loopback_hci_drills():
    script = ROOT / "deploy/scripts/deploy-digitalocean.sh"
    image = "ghcr.io/chaiwithjai/open-speaker-operations:" + "a" * 40
    environment = {
        **os.environ,
        "SPEAKEROPS_SKIP_PULL": "true",
        "SPEAKEROPS_COMPOSE_PROJECT": "speakerops-hci",
        "SPEAKEROPS_PUBLIC_URL": "https://loop.dharmicdata.org",
    }
    production = subprocess.run(
        [str(script), image], env=environment, capture_output=True, text=True
    )
    assert production.returncode == 2
    assert "allowed only for a loopback drill" in production.stderr

    environment.update(
        SPEAKEROPS_PUBLIC_URL="http://127.0.0.1:38001",
        SPEAKEROPS_COMPOSE_PROJECT="speakerops",
    )
    non_hci = subprocess.run([str(script), image], env=environment, capture_output=True, text=True)
    assert non_hci.returncode == 2
    assert "allowed only for a speakerops-hci project" in non_hci.stderr

    drill = (ROOT / "deploy/scripts/drill-image-rollback.sh").read_text()
    assert 'SPEAKEROPS_SKIP_PULL="${SPEAKEROPS_SKIP_PULL:-false}"' in drill


def test_recovery_tools_resolve_an_installed_root_layout(tmp_path):
    app_dir = tmp_path / "speakerops"
    app_dir.mkdir()
    for name in (
        "deploy-digitalocean.sh",
        "drill-image-rollback.sh",
        "verify-restore.sh",
        "smoke_journey.py",
    ):
        source = (
            ROOT / "deploy" / ("smoke_journey.py" if name.endswith(".py") else f"scripts/{name}")
        )
        shutil.copy2(source, app_dir / name)
    (app_dir / "docker-compose.yml").write_text("services: {}\n")

    backup = app_dir / "backups" / "speakerops-20260809T120000Z"
    backup.mkdir(parents=True)
    for name in ("database.dump", "media.tar.gz", "SHA256SUMS"):
        (backup / name).touch()
    restore = subprocess.run(
        [str(app_dir / "verify-restore.sh"), "--backup", str(backup)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "DRY RUN: would restore" in restore.stdout

    current = "ghcr.io/chaiwithjai/open-speaker-operations:" + "a" * 40
    previous = "ghcr.io/chaiwithjai/open-speaker-operations:" + "b" * 40
    (app_dir / ".env").write_text(f"APP_IMAGE={current}\n")
    rollback = subprocess.run(
        [
            str(app_dir / "drill-image-rollback.sh"),
            "--current",
            current,
            "--previous",
            previous,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "DRY RUN: would deploy and smoke" in rollback.stdout


def test_no_pull_preflight_records_full_local_image_id_before_backup(tmp_path):
    app_dir = tmp_path / "speakerops"
    fake_bin = tmp_path / "bin"
    app_dir.mkdir()
    fake_bin.mkdir()
    shutil.copy2(ROOT / "deploy/scripts/deploy-digitalocean.sh", app_dir / "deploy.sh")
    (app_dir / "docker-compose.yml").write_text("services: {}\n")
    image = "ghcr.io/chaiwithjai/open-speaker-operations:" + "a" * 40
    (app_dir / ".env").write_text(f"APP_IMAGE={image}\n")
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1 $2" = "image inspect" ]; then\n'
        '  if [ "${FAKE_DOCKER_MISSING:-false}" = "true" ]; then exit 1; fi\n'
        "  printf 'sha256:%064d\\n' 0\n"
        "  exit 0\n"
        "fi\n"
        "exit 9\n"
    )
    fake_docker.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SPEAKEROPS_APP_DIR": str(app_dir),
        "SPEAKEROPS_SKIP_PULL": "true",
        "SPEAKEROPS_COMPOSE_PROJECT": "speakerops-hci-contract",
        "SPEAKEROPS_PUBLIC_URL": "http://127.0.0.1:48001",
    }
    result = subprocess.run(
        [str(app_dir / "deploy.sh"), image],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 9
    assert "no registry immutability is claimed" in result.stdout
    assert f"{image} resolves to local image sha256:" in result.stdout
    assert not list(app_dir.glob(".env.previous.*"))

    missing_environment = {**environment, "FAKE_DOCKER_MISSING": "true"}
    missing = subprocess.run(
        [str(app_dir / "deploy.sh"), image],
        env=missing_environment,
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 2
    assert "Preloaded local rehearsal image is unavailable" in missing.stderr
    assert not list(app_dir.glob(".env.previous.*"))


def test_production_pull_contract_records_a_registry_digest():
    source = (ROOT / "deploy/scripts/deploy-digitalocean.sh").read_text()
    assert ".RepoDigests" in source
    assert "Registry image verified:" in source
    assert "Pulled image did not expose the expected GHCR RepoDigest" in source


def test_production_deploy_imports_and_verifies_conference_memory_before_smoke():
    source = (ROOT / "deploy/scripts/deploy-digitalocean.sh").read_text()
    coverage = source.index("speakerops_history_coverage")
    history_import = source.index("speakerops_import_history")
    protected_smoke = source.index('python3 "$smoke_script"')

    assert coverage < history_import < protected_smoke
    assert '--contract "$history_contract" --strict' in source
    assert "--prune --confirm-prune --verify" in source
