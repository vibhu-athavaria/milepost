"""Git hooks and the merge driver config (SPEC section 10)."""

import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

MARKER = "# managed-by: milepost"
MERGE_DRIVER = "milepost merge-driver %O %A %B %P"
GITATTRIBUTES_LINE = "kb/**/*.md merge=milepost"

_GUARD = (
    "command -v milepost >/dev/null 2>&1 "
    '|| { echo "milepost: not installed, skipping" >&2; exit 0; }'
)
HOOKS = {
    "post-merge": (
        f'{_GUARD}\nmilepost index || echo "milepost: index failed (non-blocking)" >&2\nexit 0\n'
    ),
    "post-checkout": (
        f'{_GUARD}\nmilepost index || echo "milepost: index failed (non-blocking)" >&2\nexit 0\n'
    ),
    "pre-commit": f"{_GUARD}\nexec milepost check\n",
}


@dataclass
class HooksReport:
    written: list[str] = field(default_factory=list)
    skipped_reason: str = ""
    snippet: str = ""


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    return done.stdout.strip()


def _hooks_dir(root: Path) -> Path:
    return (root / _git(root, "rev-parse", "--git-path", "hooks")).resolve()


def _snippet() -> str:
    lines = ["Add these to your hook manager, so milepost still runs:"]
    lines += [f"  {name}: {body.splitlines()[-1]}" for name, body in HOOKS.items()]
    lines.append(f"And set the merge driver: git config merge.milepost.driver '{MERGE_DRIVER}'")
    return "\n".join(lines)


def _is_ours(path: Path) -> bool:
    return path.is_file() and MARKER in path.read_text(encoding="utf-8")


def install_hooks(root: Path) -> HooksReport:
    """Write the three hooks and set the merge driver, unless another tool owns the hooks."""
    if _git(root, "config", "core.hooksPath"):
        return HooksReport(
            skipped_reason="core.hooksPath is set, so another tool manages hooks",
            snippet=_snippet(),
        )
    directory = _hooks_dir(root)
    foreign = [n for n in HOOKS if (directory / n).exists() and not _is_ours(directory / n)]
    if foreign:
        return HooksReport(
            skipped_reason=f"existing hook not written by milepost: {', '.join(foreign)}",
            snippet=_snippet(),
        )
    directory.mkdir(parents=True, exist_ok=True)
    report = HooksReport()
    for name, body in HOOKS.items():
        path = directory / name
        path.write_text(f"#!/bin/sh\n{MARKER}\n{body}", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        report.written.append(name)
    _git(root, "config", "merge.milepost.name", "milepost note merge")
    _git(root, "config", "merge.milepost.driver", MERGE_DRIVER)
    attributes = root / ".gitattributes"
    existing = attributes.read_text(encoding="utf-8") if attributes.is_file() else ""
    if GITATTRIBUTES_LINE not in existing.splitlines():
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        attributes.write_text(f"{existing}{prefix}{GITATTRIBUTES_LINE}\n", encoding="utf-8")
    return report


def uninstall_hooks(root: Path) -> list[str]:
    """Remove hooks carrying the milepost marker and the merge driver config. Returns removed."""
    directory = _hooks_dir(root)
    removed = []
    for name in HOOKS:
        path = directory / name
        if _is_ours(path):
            path.unlink()
            removed.append(name)
    if removed:
        _git(root, "config", "--unset", "merge.milepost.driver")
        _git(root, "config", "--unset", "merge.milepost.name")
    return removed
