import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/developer_doctor.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("speakerops_developer_doctor", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_macos_doctor_finds_dataless_metadata_without_reading_contents(tmp_path):
    module = _load_tool()
    hydrated = tmp_path / "hydrated.txt"
    placeholder = tmp_path / "private.env"
    nested = tmp_path / "cache"
    nested.mkdir()
    hydrated.write_text("normal")
    placeholder.write_text("API_TOKEN=must-never-appear")

    def fake_stat(path):
        metadata = os.stat(path, follow_symlinks=False)
        return SimpleNamespace(
            st_mode=metadata.st_mode,
            st_flags=module.SF_DATALESS if Path(path) == placeholder else 0,
        )

    status, report = module.run_doctor([tmp_path], system_name="Darwin", stat_func=fake_stat)

    assert status == 1
    assert "dataless=1" in report
    assert "private.env" in report
    assert "must-never-appear" not in report
    assert hydrated.read_text() == "normal"
    assert placeholder.read_text() == "API_TOKEN=must-never-appear"


def test_non_macos_doctor_is_a_portable_noop(tmp_path):
    module = _load_tool()

    def forbidden_stat(_path):
        raise AssertionError("non-macOS must not scan the workspace")

    status, report = module.run_doctor([tmp_path], system_name="Linux", stat_func=forbidden_stat)

    assert status == 0
    assert report == "File Provider dataless check skipped: this host is not macOS."


def test_dataless_root_is_reported_without_entering_it(tmp_path, monkeypatch):
    module = _load_tool()
    real_metadata = os.stat(tmp_path, follow_symlinks=False)

    def dataless_root(_path):
        return SimpleNamespace(st_mode=real_metadata.st_mode, st_flags=module.SF_DATALESS)

    def forbidden_scandir(_path):
        raise AssertionError("a dataless directory must not be traversed")

    monkeypatch.setattr(module.os, "scandir", forbidden_scandir)
    status, report = module.run_doctor([tmp_path], system_name="Darwin", stat_func=dataless_root)

    assert status == 1
    assert "dataless=1" in report


def test_macos_doctor_passes_hydrated_tree_and_reports_missing_root(tmp_path):
    module = _load_tool()
    (tmp_path / "source.py").write_text("print('ok')\n")

    passed, passed_report = module.run_doctor([tmp_path], system_name="Darwin")
    missing, missing_report = module.run_doctor([tmp_path / "missing"], system_name="Darwin")

    assert passed == 0
    assert "dataless=0" in passed_report
    assert passed_report.endswith("File Provider dataless check passed.")
    assert missing == 2
    assert "root does not exist" in missing_report


def test_workspace_storage_contract_is_documented_and_make_target_is_wired():
    contributing = (ROOT / "CONTRIBUTING.md").read_text()
    makefile = (ROOT / "Makefile").read_text()

    assert "$HOME/Developer/speakerops-workspace" in contributing
    assert "$HOME/.config/speakerops" in contributing
    assert "$HOME/Library/Caches/speakerops" in contributing
    assert "developer_doctor.py" in contributing
    assert "doctor:" in makefile
    assert "tools/developer_doctor.py" in makefile
