"""`milepost uninstall`: take out what `milepost init` and `hooks install` added.

Dry run unless applied. Removes only what milepost wrote and a person has not changed; the notes
are kept unless asked, and are never deleted while they have uncommitted changes. Files a person
owns (CLAUDE.md, CODEOWNERS, a hook manager) are listed, never edited.
"""

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from milepost.config import load_config_or_default
from milepost.errors import MilepostError
from milepost.services.coverage import CONFIG_NAME
from milepost.services.hooks import (
    GITATTRIBUTES_LINE,
    installed_hooks,
    merge_driver_configured,
    uninstall_hooks,
    unset_merge_driver,
)
from milepost.services.init import WORKFLOW_PATH, WORKFLOW_TEMPLATE

SNIPPET_HEADING = "## Codebase knowledge base (milepost)"
# Keep in step with init.GITIGNORE_LINES; the second line was written by older versions.
KB_GITIGNORE_LINES = ["kb/.index/", "kb/.progress.json"]
OWNERS_FILES = [".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"]
_VERSION = re.compile(r"milepost==[\w.]+")


@dataclass
class UninstallReport:
    remove: list[str] = field(default_factory=list)
    keep: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)
    blocked: str = ""
    applied: bool = False
    failed: str = ""
    done: list[str] = field(default_factory=list)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    return done.stdout


def _without_lines(path: Path, drop: list[str]) -> bool:
    """Remove exact lines; delete the file if nothing else is left. True if anything changed."""
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        lines = handle.readlines()  # keeps each line's own ending, so CRLF files stay CRLF
    kept = [line for line in lines if line.rstrip("\r\n") not in drop]
    if len(kept) == len(lines):
        return False
    if any(line.strip() for line in kept):
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.writelines(kept)
    else:
        path.unlink()
    return True


def _has_lines(path: Path, wanted: list[str]) -> bool:
    return path.is_file() and any(
        line in wanted for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
    )


def _note_files(kb: Path) -> list[Path]:
    return sorted((kb / "modules").glob("*.md")) if (kb / "modules").is_dir() else []


def run_uninstall(root: Path, delete_notes: bool, apply: bool) -> UninstallReport:
    report = UninstallReport()
    try:
        config = load_config_or_default(root / CONFIG_NAME)
    except MilepostError:  # a broken milepost.toml must not stop it being removed
        config = load_config_or_default(root / "no-such-config")
        report.keep.append(f"{CONFIG_NAME} is invalid; assumed the default notes folder `kb/`")
    kb = root / config.project.kb_dir
    kb_name = config.project.kb_dir.rstrip("/")
    gitignore_lines = sorted(
        {*KB_GITIGNORE_LINES, f"{kb_name}/.index/", f"{kb_name}/.progress.json"}
    )
    steps: list[tuple[str, Callable[[], object]]] = []  # in the order they run

    hooks = installed_hooks(root)
    if hooks:
        steps.append(
            (
                f"git hooks ({', '.join(hooks)}) and the merge driver config",
                lambda: uninstall_hooks(root),
            )
        )
    elif merge_driver_configured(root):
        steps.append(("the merge driver config", lambda: unset_merge_driver(root)))

    attributes = root / ".gitattributes"
    if _has_lines(attributes, [GITATTRIBUTES_LINE]):
        steps.append(
            (
                f"the milepost line in .gitattributes ({GITATTRIBUTES_LINE})",
                lambda: _without_lines(attributes, [GITATTRIBUTES_LINE]),
            )
        )

    ignore = root / ".gitignore"
    if _has_lines(ignore, gitignore_lines):
        steps.append(
            (
                f"the milepost lines in .gitignore ({', '.join(gitignore_lines)})",
                lambda: _without_lines(ignore, gitignore_lines),
            )
        )
    workflow = root / WORKFLOW_PATH
    if workflow.is_file():
        ours = _VERSION.sub("", workflow.read_text(encoding="utf-8")) == _VERSION.sub(
            "", WORKFLOW_TEMPLATE.read_text(encoding="utf-8")
        )
        if ours:
            steps.append((f"the CI workflow {WORKFLOW_PATH}", workflow.unlink))
        else:
            report.keep.append(
                f"{WORKFLOW_PATH}: edited since milepost wrote it; delete it yourself if unwanted"
            )

    derived = [kb / ".index", kb / ".progress.json"]
    if any(path.exists() for path in derived):
        steps.append(
            (f"the search index and progress file under {kb_name}/", lambda: _drop(derived))
        )

    config_path = root / CONFIG_NAME
    if config_path.is_file():
        steps.append((CONFIG_NAME, config_path.unlink))

    notes = _note_files(kb)
    if delete_notes and notes:
        dirty = _git(root, "status", "--porcelain", "--", f"{kb_name}/modules").strip()
        if dirty:
            report.blocked = (
                f"{kb_name}/modules/ has uncommitted changes, so the notes were not deleted "
                "and nothing was changed; commit or stash them first "
                "(deleting them would lose that work)"
            )
        else:
            steps.append((f"{len(notes)} note(s) in {kb_name}/modules/", lambda: _drop_notes(kb)))
    elif notes:
        report.keep.append(
            f"{kb_name}/ ({len(notes)} note(s)): kept as plain markdown; "
            "add --delete-notes to remove them"
        )

    report.manual = _manual_steps(root, kb_name, managed_hooks=bool(hooks))
    report.remove = [description for description, _ in steps]
    if apply and not report.blocked and steps:
        for description, action in steps:
            try:
                action()
            except OSError as error:
                report.failed = f"{description}: {error}"
                return report  # earlier steps stay done and are listed in report.done
            report.done.append(description)
        report.applied = True
    return report


def _drop(paths: list[Path]) -> None:
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def _drop_notes(kb: Path) -> None:
    for note in _note_files(kb):
        note.unlink()
    modules = kb / "modules"
    for directory in (modules, kb):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


def _manual_steps(root: Path, kb_name: str, managed_hooks: bool) -> list[str]:
    steps = []
    for name in ("CLAUDE.md", "AGENTS.md"):
        path = root / name
        if path.is_file() and SNIPPET_HEADING in path.read_text(encoding="utf-8"):
            steps.append(f"{name}: delete the section '{SNIPPET_HEADING}'")
    for name in OWNERS_FILES:
        path = root / name
        if path.is_file() and any(
            line.lstrip().startswith((f"{kb_name}/", f"/{kb_name}/"))
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        ):
            steps.append(f"{name}: delete the lines that make someone the owner of kb/")
    if _git(root, "config", "core.hooksPath").strip() and not managed_hooks:
        steps.append("your hook manager: remove the `milepost check` / `milepost index` entries")
    dotenv = root / ".env"
    if dotenv.is_file() and "MILEPOST_" in dotenv.read_text(encoding="utf-8"):
        steps.append(".env: delete the MILEPOST_* lines (the file stays ignored by git)")
    steps.append("Claude Code: stop passing --plugin-dir to the milepost plugin folder")
    return steps
