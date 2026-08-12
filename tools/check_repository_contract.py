"""Fail when repository layout drifts from the documented contributor contract."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".test-venv",
    "__pycache__",
    "backups",
    "build",
    "dist",
    "htmlcov",
    "output",
    "playwright-report",
    "test-results",
}
FORBIDDEN_SUFFIXES = {".dump", ".prof", ".pyc", ".sqlite3", ".trace"}
REQUIRED_PATHS = {
    "CONTRIBUTING.md",
    "README.md",
    "deploy/smoke_journey.py",
    "docs/README.md",
    "docs/architecture.md",
    "docs/repository-map.md",
    "docker-compose.yml",
    "tools/ci-compose-smoke.sh",
    "tools/developer_doctor.py",
}
ROOT_ALLOWLIST = {
    ".dockerignore",
    ".env.example",
    ".env.local.example",
    ".gitignore",
    "CONTRIBUTING.md",
    "Dockerfile",
    "LICENSE",
    "Makefile",
    "README.md",
    "docker-compose.yml",
    "opencode.json",
    "pyproject.toml",
    "uv.lock",
}


def tracked_paths() -> list[PurePosixPath]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        path
        for value in result.stdout.splitlines()
        if value and (ROOT / (path := PurePosixPath(value))).exists()
    ]


def main() -> None:
    paths = tracked_paths()
    path_strings = {str(path) for path in paths}
    failures = []
    for required in sorted(REQUIRED_PATHS):
        # New files are checked in the worktree before they enter Git's index.
        if required not in path_strings and not (ROOT / required).is_file():
            failures.append(f"missing required repository path: {required}")
    for path in paths:
        if path.parent == PurePosixPath(".") and path.name not in ROOT_ALLOWLIST:
            failures.append(f"unexpected repository-root file: {path}")
        if FORBIDDEN_PARTS.intersection(path.parts):
            failures.append(f"tracked generated/local artifact: {path}")
        if path.suffix in FORBIDDEN_SUFFIXES or path.name == ".coverage":
            failures.append(f"tracked generated/local artifact: {path}")
        if path.parent == PurePosixPath("tests") and re.fullmatch(r"test_m\d+\.py", path.name):
            failures.append(f"milestone-only test filename: {path}")
    compose_paths = [path for path in paths if path.name in {"compose.yaml", "docker-compose.yml"}]
    if compose_paths != [PurePosixPath("docker-compose.yml")]:
        failures.append(f"expected one canonical root Compose file, found: {compose_paths}")
    if failures:
        raise SystemExit("Repository contract failed:\n" + "\n".join(failures))
    print(f"Repository contract passed: {len(paths)} tracked paths inspected.")


if __name__ == "__main__":
    main()
