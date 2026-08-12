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
FORBIDDEN_NAME_PATTERN = re.compile(
    r"(^|[._-])(auth|cookies?|storage[._-]?state|browser[._-]?state)([._-]|$)",
    re.I,
)
SECRET_KEY_PATTERN = re.compile(
    r"(password|passphrase|api[_-]?key|authorization|cookie|set[_-]?cookie|"
    r"access[_-]?token|refresh[_-]?token|session|bearer|client[_-]?secret|"
    r"magic[_-]?(link|token)|reset[_-]?(link|token))",
    re.I,
)
LEAK_PATTERN = re.compile(
    r"sk-ant-|(?i:authorization)\s*[:=]|(?i:set-cookie)\s*:|"
    r"(?i:sessionid|csrftoken|access_token|refresh_token|client_secret)\s*[:=]|"
    r"/invitation/[A-Za-z0-9_-]+/[A-Za-z0-9_-]{24,}"
)
CORE_FILES = ("report.json", "report.html", "manual-checklist.md")
DELIVERY_FILES = (
    "README.md",
    "manual-results.json",
    "sanitized-run-config.json",
)


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
        if (
            path.name.lower() == ".env"
            or path.name.lower().endswith(".env")
            or FORBIDDEN_NAME_PATTERN.search(path.name)
        ):
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


def scan_staged(root: Path, secrets: set[str]):
    leaks = []
    for path in root.rglob("*"):
        if not path.is_file() or path.name == "SHA256SUMS":
            continue
        text = path.read_text(errors="ignore")
        if any(secret in text for secret in secrets) or LEAK_PATTERN.search(text):
            leaks.append(path.relative_to(root).as_posix())
    if leaks:
        raise ValueError(f"post-stage security scan failed for {len(leaks)} file(s)")


def stage(
    source: Path,
    destination: Path,
    secrets: set[str],
    *,
    delivery_source: Path | None = None,
    screenshot_allowlist: Path | None = None,
) -> dict:
    source_resolved = source.resolve()
    destination_resolved = destination.resolve()
    if destination_resolved == source_resolved or source_resolved in destination_resolved.parents:
        raise ValueError("destination must be outside the source tree")
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
    for name in CORE_FILES[1:]:
        source_path = source / name
        clean, count = sanitize_string(source_path.read_text(), secrets)
        (destination / name).write_text(clean)
        replacements += count
        staged.append(name)
    screenshots = []
    if delivery_source:
        for name in DELIVERY_FILES:
            source_path = delivery_source / name
            if not source_path.is_file():
                raise ValueError(f"missing delivery artifact: {name}")
            clean, count = sanitize_string(source_path.read_text(), secrets)
            (destination / name).write_text(clean)
            replacements += count
            staged.append(name)
        if not screenshot_allowlist or not screenshot_allowlist.is_file():
            raise ValueError("delivery-ready staging requires a screenshot allowlist")
        allowlist = json.loads(screenshot_allowlist.read_text())
        if not isinstance(allowlist, list) or not allowlist:
            raise ValueError("screenshot allowlist must contain reviewed entries")
        for entry in allowlist:
            source_path = Path(entry["source"]).resolve()
            expected = entry["sha256"]
            if entry.get("review_status") != "approved" or file_hash(source_path) != expected:
                raise ValueError("screenshot allowlist review/hash mismatch")
            relative = Path("screenshots") / Path(entry["destination"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("screenshot destination must be relative and bounded")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source_path.read_bytes())
            screenshots.append(relative.as_posix())
            staged.append(relative.as_posix())
    after = tree_manifest(source)
    if before != after:
        raise RuntimeError("source tree changed during staging")
    scan_staged(destination, secrets)
    receipt = {
        "schema": "speakerops.sbek-bundle-audit.v1",
        "source_file_count": len(before),
        "scenario_count": len(scenarios),
        "staged_files": sorted(staged),
        "staged_file_count": len(staged),
        "selected_screenshots": sorted(screenshots),
        "delivery_ready": bool(delivery_source),
        "omitted_source_file_count": len(before) - len(staged),
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
    parser.add_argument("--delivery-source", type=Path)
    parser.add_argument("--screenshot-allowlist", type=Path)
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
    receipt = stage(
        args.source,
        args.destination,
        secrets,
        delivery_source=args.delivery_source,
        screenshot_allowlist=args.screenshot_allowlist,
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
