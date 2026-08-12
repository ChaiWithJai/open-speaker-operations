#!/usr/bin/env python3
"""Audit or stage an SBEK evidence bundle without mutating its source tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SCENARIO_PATTERN = re.compile(r"^[A-Z]{3}-S\d+$")
INVITATION_TOKEN = re.compile(r"(/invitation/[A-Za-z0-9_-]+/)[A-Za-z0-9_-]{32}(?=[^A-Za-z0-9_-]|$)")
FORBIDDEN_NAMES = {".auth", ".env", "cookies.json", "storage-state.json"}
SECRET_KEY_PATTERN = re.compile(r"(password|api[_-]?key|authorization|cookie)", re.I)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def sanitize_string(value: str, secrets: set[str]) -> tuple[str, int]:
    replacements = 0
    for secret in secrets:
        value, count = re.subn(re.escape(secret), "[REDACTED_SECRET]", value)
        replacements += count
    value, count = INVITATION_TOKEN.subn(r"\1[REDACTED_INVITATION_TOKEN]", value)
    return value, replacements + count


def sanitize_value(value, secrets: set[str]):
    if isinstance(value, dict):
        result = {}
        replacements = 0
        for key, item in value.items():
            if SECRET_KEY_PATTERN.fullmatch(str(key)) and isinstance(item, str) and item:
                result[key] = "[REDACTED_SECRET]"
                replacements += 1
                continue
            result[key], count = sanitize_value(item, secrets)
            replacements += count
        return result, replacements
    if isinstance(value, list):
        result = []
        replacements = 0
        for item in value:
            clean, count = sanitize_value(item, secrets)
            result.append(clean)
            replacements += count
        return result, replacements
    if isinstance(value, str):
        return sanitize_string(value, secrets)
    return value, 0


def validate_source(root: Path) -> list[Path]:
    if not root.is_dir():
        raise ValueError("source must be a directory")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"symlinks are forbidden: {path.relative_to(root)}")
        if path.name in FORBIDDEN_NAMES:
            raise ValueError(f"auth/environment artifact is forbidden: {path.relative_to(root)}")
    scenarios = sorted(
        path.parent
        for path in root.glob("*/evidence.json")
        if SCENARIO_PATTERN.fullmatch(path.parent.name)
    )
    if len(scenarios) != 20:
        raise ValueError(f"expected exactly 20 scenario evidence files, found {len(scenarios)}")
    for required in ("report.json", "report.html", "manual-checklist.md"):
        if not (root / required).is_file():
            raise ValueError(f"missing required artifact: {required}")
    return scenarios


def stage(source: Path, destination: Path, secrets: set[str]) -> dict:
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("destination must not exist or must be empty")
    before = tree_manifest(source)
    scenarios = validate_source(source)
    destination.mkdir(parents=True, exist_ok=True)
    replacements = 0
    staged = []
    for source_path in [source / "report.json", *[p / "evidence.json" for p in scenarios]]:
        relative = source_path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(source_path.read_text())
        clean, count = sanitize_value(data, secrets)
        target.write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n")
        replacements += count
        staged.append(relative.as_posix())
    for name in ("report.html", "manual-checklist.md"):
        source_path = source / name
        clean, count = sanitize_string(source_path.read_text(), secrets)
        (destination / name).write_text(clean)
        replacements += count
        staged.append(name)
    after = tree_manifest(source)
    if before != after:
        raise RuntimeError("source tree changed during staging")
    receipt = {
        "schema": "speakerops.sbek-bundle-audit.v1",
        "source_file_count": len(before),
        "scenario_count": len(scenarios),
        "staged_files": sorted(staged),
        "redaction_count": replacements,
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(before, sort_keys=True).encode()
        ).hexdigest(),
    }
    (destination / "audit-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    manifest = tree_manifest(destination)
    (destination / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in manifest.items())
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--secret-file", type=Path, action="append", default=[])
    parser.add_argument("--credential-config", type=Path)
    args = parser.parse_args()
    scenarios = validate_source(args.source)
    if not args.destination:
        print(json.dumps({"scenario_count": len(scenarios), "verified": True}))
        return 0
    secrets = {
        line.strip()
        for secret_file in args.secret_file
        for line in secret_file.read_text().splitlines()
        if line.strip()
    }
    if args.credential_config:
        config = json.loads(args.credential_config.read_text())
        secrets.update(
            entry["password"]
            for entry in config.get("credentials", {}).values()
            if isinstance(entry, dict) and entry.get("password")
        )
    if not secrets:
        raise ValueError("staging requires at least one explicit secret source")
    receipt = stage(args.source, args.destination, secrets)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
