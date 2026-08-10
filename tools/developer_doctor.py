"""Non-destructively detect macOS File Provider placeholders in workspace trees.

The doctor inspects directory entries and file metadata only. It never opens,
downloads, modifies, deletes, or prints file contents.
"""

from __future__ import annotations

import argparse
import os
import platform
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

SF_DATALESS = getattr(stat, "SF_DATALESS", 0x40000000)


@dataclass(frozen=True)
class ScanResult:
    root: Path
    inspected: int
    dataless: tuple[Path, ...]
    errors: tuple[str, ...]


def _lstat(path: Path):
    return os.stat(path, follow_symlinks=False)


def scan_dataless(
    root: Path,
    *,
    stat_func: Callable[[Path], object] = _lstat,
) -> ScanResult:
    """Walk *root* using metadata only and return File Provider placeholders.

    A dataless directory is reported but not entered, which avoids asking File
    Provider to materialize its descendants merely for diagnosis.
    """

    root = root.expanduser().resolve()
    try:
        root_metadata = stat_func(root)
    except FileNotFoundError:
        return ScanResult(root=root, inspected=0, dataless=(), errors=("root does not exist",))
    except OSError as error:
        return ScanResult(
            root=root,
            inspected=0,
            dataless=(),
            errors=(f"root metadata: {error.__class__.__name__}",),
        )
    if getattr(root_metadata, "st_flags", 0) & SF_DATALESS:
        return ScanResult(root=root, inspected=1, dataless=(root,), errors=())
    if not stat.S_ISDIR(root_metadata.st_mode):
        return ScanResult(root=root, inspected=1, dataless=(), errors=())

    pending = [root]
    inspected = 1
    dataless = []
    errors = []
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as error:
            errors.append(f"{directory}: {error.__class__.__name__}")
            continue
        for entry in entries:
            path = Path(entry.path)
            try:
                metadata = stat_func(path)
            except OSError as error:
                errors.append(f"{path}: {error.__class__.__name__}")
                continue
            inspected += 1
            if getattr(metadata, "st_flags", 0) & SF_DATALESS:
                dataless.append(path)
                continue
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)

    return ScanResult(
        root=root,
        inspected=inspected,
        dataless=tuple(sorted(dataless)),
        errors=tuple(errors),
    )


def format_report(results: Iterable[ScanResult], *, max_examples: int = 10) -> str:
    """Format metadata-only findings; file contents are never accepted or rendered."""

    lines = []
    for result in results:
        lines.append(
            f"workspace={result.root} inspected={result.inspected} "
            f"dataless={len(result.dataless)} errors={len(result.errors)}"
        )
        for path in result.dataless[:max_examples]:
            lines.append(f"  dataless: {path.relative_to(result.root)}")
        if len(result.dataless) > max_examples:
            lines.append(f"  ... {len(result.dataless) - max_examples} more")
        for error in result.errors[:max_examples]:
            lines.append(f"  unreadable metadata: {error}")
    return "\n".join(lines)


def run_doctor(
    roots: Iterable[Path],
    *,
    system_name: str | None = None,
    stat_func: Callable[[Path], object] = _lstat,
) -> tuple[int, str]:
    """Return a process-style status and human-readable diagnostic report."""

    system_name = system_name or platform.system()
    if system_name != "Darwin":
        return 0, "File Provider dataless check skipped: this host is not macOS."

    results = [scan_dataless(root, stat_func=stat_func) for root in roots]
    report = format_report(results)
    if any(result.errors for result in results):
        return 2, report
    if any(result.dataless for result in results):
        return 1, report
    return 0, report + "\nFile Provider dataless check passed."


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect macOS File Provider dataless placeholders without hydrating them."
    )
    parser.add_argument(
        "roots",
        metavar="PATH",
        nargs="*",
        type=Path,
        default=[Path.cwd()],
        help="workspace roots to inspect (default: current directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status, report = run_doctor(args.roots)
    print(report)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
