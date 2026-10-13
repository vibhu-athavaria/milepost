"""What git knows about a change range: waiver trailers, changed files, files at the base."""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from milepost.errors import UsageError

_WAIVER = re.compile(r"^KB-Waive:[ \t]*(\S+)(?:[ \t]+(\S.*?))?[ \t]*$", re.MULTILINE)


@dataclass
class Changes:
    added: set[str] = field(default_factory=set)
    modified: set[str] = field(default_factory=set)
    deleted: set[str] = field(default_factory=set)

    @property
    def all(self) -> set[str]:
        return self.added | self.modified | self.deleted


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise UsageError("git is not installed or not on PATH") from error
    if done.returncode != 0:
        raise UsageError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def read_waivers(root: Path, base: str) -> dict[str, str]:
    """Map waiver subject to reason, from KB-Waive trailers in commits between base and HEAD."""
    waivers: dict[str, str] = {}
    for message in _git(root, "log", "--format=%B%x00", f"{base}..HEAD").split("\x00"):
        for match in _WAIVER.finditer(message):
            subject, reason = match.group(1), match.group(2)
            if not reason:
                raise UsageError(f"KB-Waive trailer for '{subject}' has no reason")
            waivers[subject] = reason
    return waivers


def _parse_name_status(output: str, changes: Changes) -> Changes:
    tokens = output.split("\x00")
    for status, path in zip(tokens[0::2], tokens[1::2], strict=False):
        bucket = {"A": changes.added, "D": changes.deleted}.get(status[:1], changes.modified)
        bucket.add(path)
    return changes


def changed_files(root: Path, base: str) -> Changes:
    output = _git(root, "diff", "--name-status", "--no-renames", "-z", f"{base}...HEAD")
    return _parse_name_status(output, Changes())


def files_at(root: Path, ref: str, directory: str) -> list[str]:
    """Tracked file paths under `directory` at `ref`."""
    return [
        line
        for line in _git(root, "ls-tree", "-r", "--name-only", ref, "--", directory).splitlines()
        if line
    ]


def _has_head(root: Path) -> bool:
    done = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=root, capture_output=True, check=False
    )
    return done.returncode == 0


def working_tree_changes(root: Path) -> Changes:
    """Files changed against HEAD (staged or not) plus untracked files that are not ignored.

    In a repository with no commits yet, every tracked or untracked file counts as added."""
    changes = Changes()
    if _has_head(root):
        _parse_name_status(
            _git(root, "diff", "--name-status", "--no-renames", "-z", "HEAD"), changes
        )
    else:
        changes.added.update(name for name in _git(root, "ls-files", "-z").split("\x00") if name)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    changes.added.update(path for path in untracked.split("\x00") if path)
    return changes


def repo_files(root: Path) -> list[str]:
    """Tracked files plus untracked files that git does not ignore, sorted, existing on disk."""
    tracked = _git(root, "ls-files", "-z")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    names = {name for name in (tracked + "\x00" + untracked).split("\x00") if name}
    return sorted(name for name in names if (root / name).is_file())
