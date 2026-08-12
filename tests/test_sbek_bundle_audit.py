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
