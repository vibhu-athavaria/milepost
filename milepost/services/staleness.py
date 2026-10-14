"""Is a note out of date? Judged from git history, with nothing stored in the note (SPEC 6).

A note is *stale* when a file it covers changed after the note was last touched. "Touched" is
the note's latest commit, or an uncommitted edit to the note. So the answer needs no stored
hash, which means two pull requests that change different files of one module cannot conflict
over it, and a comment-only edit costs one line in the note, not a re-hash of everything.

The rule, per module:
- the note and a covered file both have uncommitted edits: stale if the code was saved after the
  note (by file modification time), otherwise fresh;
- only the note has uncommitted edits: fresh (someone touched it just now);
- only covered files have uncommitted edits: stale;
- otherwise stale if some commit that touched a covered file is not reachable from the latest
  commit that touched the note. That also handles merged branches: code that landed from
  another branch after the note's last update is found even if its date is older.
This is deliberately an approximation of "the note was written against this code": it cannot
tell whether the note's author read the new code. Review is what vouches for the prose.
"""

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from milepost.config import Config
from milepost.core.glob import matches_any
from milepost.errors import UsageError


@dataclass(frozen=True)
class Staleness:
    stale: bool
    reason: str = ""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise UsageError("git is not installed or not on PATH") from error


def _require_full_history(root: Path) -> None:
    done = _git(root, "rev-parse", "--is-shallow-repository")
    if done.returncode == 0 and done.stdout.strip() == "true":
        raise UsageError(
            "this is a shallow clone, so staleness cannot be judged; fetch full history"
        )


def _dirty_paths(root: Path) -> set[str]:
    """Files under `root` with uncommitted changes, as paths relative to `root`."""
    prefix = _git(root, "rev-parse", "--show-prefix").stdout.strip()
    done = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
    if done.returncode != 0:
        raise UsageError(f"git status failed: {done.stderr.strip()}")
    paths = {entry[3:] for entry in done.stdout.split("\x00") if len(entry) > 3}
    return {p[len(prefix) :] for p in paths if p.startswith(prefix)}


def _pathspecs(sources: list[str], ignore: list[str], kb_dir: str) -> list[str]:
    specs = [f":(glob){s}" for s in sources]
    specs += [f":(exclude,glob){i}" for i in ignore]
    specs.append(f":(exclude,glob){kb_dir}/**")  # a note is never "covered code"
    return specs


def _latest_commit(root: Path, path: str) -> str:
    done = _git(root, "log", "-1", "--format=%H", "--", path)
    if done.returncode != 0:
        raise UsageError(f"git log failed: {done.stderr.strip()}")
    return done.stdout.strip()


def _code_commit_after(root: Path, note_commit: str, pathspecs: list[str]) -> str:
    """A commit that touched covered code and is not reachable from `note_commit`, or ''."""
    done = _git(root, "log", "-1", "--format=%H", f"{note_commit}..HEAD", "--", *pathspecs)
    if done.returncode != 0:
        raise UsageError(f"git log failed: {done.stderr.strip()}")
    return done.stdout.strip()


def _code_saved_after_note(root: Path, note_rel: str, code_paths: list[str]) -> str:
    """The first dirty covered file saved after the note was, else ''."""
    note_time = (root / note_rel).stat().st_mtime_ns
    for path in code_paths:
        file = root / path
        if file.exists() and file.stat().st_mtime_ns > note_time:
            return path
    return ""


def module_staleness(
    root: Path, config: Config, only: Iterable[str] | None = None
) -> dict[str, Staleness]:
    """Staleness of each module whose note file exists (all modules, or just those in `only`).

    Raises UsageError outside a git repository or in a shallow clone."""
    _require_full_history(root)
    kb = config.project.kb_dir.rstrip("/")
    dirty = _dirty_paths(root)
    wanted = set(only) if only is not None else None
    result: dict[str, Staleness] = {}
    for module_id, module in config.modules.items():
        if wanted is not None and module_id not in wanted:
            continue
        note_rel = f"{kb}/modules/{module_id}.md"
        if not (root / note_rel).is_file():
            continue
        code_dirty = sorted(
            p
            for p in dirty
            if not p.startswith(f"{kb}/")
            and matches_any(p, module.sources)
            and not matches_any(p, config.structure.ignore)
        )
        if note_rel in dirty:
            later = _code_saved_after_note(root, note_rel, code_dirty) if code_dirty else ""
            result[module_id] = (
                Staleness(True, f"{later} was edited after the note was")
                if later
                else Staleness(False)
            )
            continue
        if code_dirty:
            result[module_id] = Staleness(True, f"uncommitted changes to {code_dirty[0]}")
            continue
        note_commit = _latest_commit(root, note_rel)
        newer = (
            _code_commit_after(
                root, note_commit, _pathspecs(module.sources, config.structure.ignore, kb)
            )
            if note_commit
            else ""
        )
        if newer:
            result[module_id] = Staleness(
                True, f"covered code changed in {newer[:8]} after the note was last updated"
            )
        else:
            result[module_id] = Staleness(False)
    return result
