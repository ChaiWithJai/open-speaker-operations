import json
from pathlib import Path

import pytest

from tools.sbek_bundle_audit import main, stage, validate_source


def make_source(root: Path):
    (root / "report.json").write_text(json.dumps({"password": "secret-value"}))
    (root / "report.html").write_text(
        "secret-value /invitation/demo/abcdefghijklmnopqrstuvwxyzABCDEF"
    )
    (root / "manual-checklist.md").write_text("manual")
    (root / "unselected-screenshot.png").write_bytes(b"not implicitly staged")
    for index in range(20):
        scenario = root / f"TST-S{index}"
        scenario.mkdir()
        (scenario / "evidence.json").write_text(
            json.dumps({"text": "secret-value", "cookie": "session-value"})
        )


def test_stage_recursively_sanitizes_and_preserves_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_source(source)
    original = (source / "report.json").read_bytes()
    destination = tmp_path / "destination"

    receipt = stage(source, destination, {"secret-value"})

    assert receipt["scenario_count"] == 20
    assert receipt["delivery_ready"] is False
    assert receipt["omitted_source_file_count"] > 0
    assert receipt["redaction_count"] >= 42
    assert (source / "report.json").read_bytes() == original
    staged_text = "\n".join(
        path.read_text(errors="ignore") for path in destination.rglob("*") if path.is_file()
    )
    assert "secret-value" not in staged_text
    assert "session-value" not in staged_text
    assert "abcdefghijklmnopqrstuvwxyzABCDEF" not in staged_text
    assert "[REDACTED_SECRET]" in staged_text
    assert (destination / "SHA256SUMS").is_file()


def test_validate_source_rejects_wrong_scenario_count(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_source(source)
    (source / "TST-S19" / "evidence.json").unlink()
    with pytest.raises(ValueError, match="exactly 20"):
        validate_source(source)


def test_validate_source_rejects_auth_artifacts_and_symlinks(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_source(source)
    (source / ".auth").write_text("private")
    with pytest.raises(ValueError, match="forbidden"):
        validate_source(source)
    (source / ".auth").unlink()
    (source / "escape").symlink_to(source / "report.json")
    with pytest.raises(ValueError, match="symlinks"):
        validate_source(source)


def test_stage_rejects_destination_inside_source_before_writing(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_source(source)
    destination = source / "staged"
    with pytest.raises(ValueError, match="outside"):
        stage(source, destination, {"secret-value"})
    assert not destination.exists()


def test_stage_rejects_nested_destination_without_creating_parent(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_source(source)
    parent = source / "new-parent"
    with pytest.raises(ValueError, match="outside"):
        stage(source, parent / "out", {"secret-value"})
    assert not parent.exists()


@pytest.mark.parametrize(
    "name",
    ["prod.env", "AUTH_STATE.json", "browser-state.json", "Cookies.JSON"],
)
def test_validate_source_rejects_alternate_auth_artifact_names(tmp_path, name):
    source = tmp_path / "source"
    source.mkdir()
    make_source(source)
    (source / name).write_text("private")
    with pytest.raises(ValueError, match="forbidden"):
        validate_source(source)


def test_cli_reads_credentials_without_copying_config(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    make_source(source)
    config = tmp_path / "evalconfig.json"
    config.write_text(json.dumps({"credentials": {"speaker": {"password": "secret-value"}}}))
    destination = tmp_path / "destination"
    monkeypatch.setattr(
        "sys.argv",
        [
            "sbek_bundle_audit.py",
            str(source),
            "--destination",
            str(destination),
            "--credential-config",
            str(config),
        ],
    )
    assert main() == 0
    assert not (destination / config.name).exists()


def test_delivery_ready_requires_complete_metadata_and_reviewed_screenshot(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_source(source)
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    (delivery / "README.md").write_text("74.4% 90.0% tested deployed")
    (delivery / "manual-results.json").write_text(json.dumps({"CFP-08": {"verdict": "pass"}}))
    (delivery / "sanitized-run-config.json").write_text(
        json.dumps(
            {
                "evaluatorRepositorySha": "a",
                "testedApplicationSha": "b",
                "currentProductionSha": "c",
                "currentProductionImageDigest": "sha256:d",
            }
        )
    )
    screenshot = tmp_path / "reviewed.png"
    mobile = tmp_path / "mobile.png"
    screenshot.write_bytes(b"reviewed screenshot")
    mobile.write_bytes(b"reviewed mobile")
    allowlist = tmp_path / "allowlist.json"
    from tools.sbek_bundle_audit import file_hash

    allowlist.write_text(
        json.dumps(
            [
                {
                    "source": str(screenshot),
                    "destination": "desktop/reviewed.png",
                    "viewport": "desktop",
                    "review_status": "approved",
                    "sha256": file_hash(screenshot),
                },
                {
                    "source": str(mobile),
                    "destination": "mobile/reviewed.png",
                    "viewport": "mobile",
                    "review_status": "approved",
                    "sha256": file_hash(mobile),
                },
            ]
        )
    )
    receipt = stage(
        source,
        tmp_path / "destination",
        {"secret-value"},
        delivery_source=delivery,
        screenshot_allowlist=allowlist,
    )
    assert receipt["delivery_ready"] is True
    assert receipt["selected_screenshots"] == [
        "screenshots/desktop/reviewed.png",
        "screenshots/mobile/reviewed.png",
    ]


def test_post_stage_scan_rejects_unredacted_access_token(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_source(source)
    (source / "report.html").write_text("access_token=unreviewed")
    with pytest.raises(ValueError, match="security scan"):
        stage(source, tmp_path / "destination", {"different-secret"})
    assert not (tmp_path / "destination").exists()
    assert not list(tmp_path.glob(".destination.staging-*"))


@pytest.mark.parametrize(
    "leak",
    [
        "password=unknown-secret",
        "api_key=also-unknown",
        "Bearer token-value",
        "magic_token=unknown-magic",
    ],
)
def test_post_stage_scan_rejects_unknown_text_secrets(tmp_path, leak):
    source = tmp_path / "source"
    source.mkdir()
    make_source(source)
    (source / "report.html").write_text(leak)
    destination = tmp_path / "destination"
    with pytest.raises(ValueError, match="security scan"):
        stage(source, destination, {"different-secret"})
    assert not destination.exists()


def test_validate_source_rejects_dotenv_environment_suffix(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_source(source)
    (source / ".env.production").write_text("private")
    with pytest.raises(ValueError, match="forbidden"):
        validate_source(source)


def test_delivery_json_is_structurally_sanitized(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    make_source(source)
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    (delivery / "README.md").write_text("74.4% 90.0% tested deployed")
    (delivery / "manual-results.json").write_text(
        json.dumps({"CFP-08": {"verdict": "pass", "password": "unknown-secret"}})
    )
    (delivery / "sanitized-run-config.json").write_text(
        json.dumps(
            {
                "evaluatorRepositorySha": "a",
                "testedApplicationSha": "b",
                "currentProductionSha": "c",
                "currentProductionImageDigest": "sha256:d",
                "password": "unknown-secret",
            }
        )
    )
    desktop = tmp_path / "desktop.png"
    mobile = tmp_path / "mobile.png"
    desktop.write_bytes(b"desktop")
    mobile.write_bytes(b"mobile")
    from tools.sbek_bundle_audit import file_hash

    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        json.dumps(
            [
                {
                    "source": str(desktop),
                    "destination": "desktop.png",
                    "viewport": "desktop",
                    "review_status": "approved",
                    "sha256": file_hash(desktop),
                },
                {
                    "source": str(mobile),
                    "destination": "mobile.png",
                    "viewport": "mobile",
                    "review_status": "approved",
                    "sha256": file_hash(mobile),
                },
            ]
        )
    )
    destination = tmp_path / "destination"
    receipt = stage(
        source,
        destination,
        {"secret-value"},
        delivery_source=delivery,
        screenshot_allowlist=allowlist,
    )
    assert receipt["delivery_ready"] is True
    assert receipt["omitted_source_file_count"] >= 0
    assert "unknown-secret" not in (destination / "manual-results.json").read_text()
    assert "unknown-secret" not in (destination / "sanitized-run-config.json").read_text()
