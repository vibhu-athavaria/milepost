"""`milepost status`: how far each module's code has moved since a person last reviewed its note
(SPEC section 8.4). Derived from git history and the notes; read-only."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from milepost.config import Config
from milepost.core.glob import matches_any
from milepost.core.notes import Note, parse_note
from milepost.errors import NoteInvalid, UsageError

MAX_EVENTS = 50


@dataclass
class ModuleStatus:
    module_id: str
    note_status: str
    never_reviewed: bool
    reviewed_by: str = ""
    reviewed_at: str = ""
    baseline: str = ""
    commits_since: int = 0
    lines_changed_since: int = 0
    agent_commits_since: int = 0


def _git(root: Path, *args: str) -> str:
    # --literal-pathspecs: file names such as app/[id]/page.tsx must not be read as globs.
    done = subprocess.run(
        ["git", "--literal-pathspecs", *args], cwd=root, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise UsageError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def _note_at(root: Path, sha: str, note_rel: str) -> Note | None:
    try:
        return parse_note(_git(root, "show", f"{sha}:{note_rel}"))
    except (NoteInvalid, UsageError):
        return None


def _reviewed_baseline(root: Path, note_rel: str) -> tuple[str, str, str] | None:
    """(commit, reviewed_by, reviewed_at) of the latest commit that recorded a review.

    A review event is a commit that added or removed a `reviewed_at` line, so a typo fix or a
    edit that does not touch the review fields does not reset the baseline. Only those events are
    inspected, newest first, so the cost does not grow with the note's whole history. Notes
    reviewed by hand, without `reviewed_at`, fall back to commits that touched the status line."""
    for pattern in ("^reviewed_at:", "^status: reviewed"):
        events = _git(
            root, "log", f"-{MAX_EVENTS}", "-G", pattern, "--format=%H", "--", note_rel
        ).split()
        for sha in events:
            note = _note_at(root, sha, note_rel)
            if note is not None and note.meta.get("status") == "reviewed":
                return (
                    sha,
                    str(note.meta.get("reviewed_by", "")),
                    str(note.meta.get("reviewed_at", "")),
                )
    return None


def _touched_files(
    root: Path, baseline: str, module_sources: list[str], ignore: list[str]
) -> list[str]:
    """Files in the module's source set now, plus files in it that changed since the baseline
    even if they are gone now, so deleted or moved code still counts as churn."""
    names = _git(root, "diff", "--name-only", "-z", baseline, "HEAD").split("\x00")
    changed = {
        n for n in names if n and matches_any(n, module_sources) and not matches_any(n, ignore)
    }
    return sorted(changed)


def _lines_changed(root: Path, baseline: str, files: list[str]) -> int:
    total = 0
    for start in range(0, len(files), 200):
        output = _git(
            root, "diff", "--numstat", baseline, "HEAD", "--", *files[start : start + 200]
        )
        for line in output.splitlines():
            added, deleted, *_ = line.split("\t")
            total += (int(added) if added.isdigit() else 0) + (
                int(deleted) if deleted.isdigit() else 0
            )
    return total


def _commit_stats(
    root: Path, baseline: str, files: list[str], patterns: list[re.Pattern[str]]
) -> tuple[int, int]:
    commits: set[str] = set()
    agent: set[str] = set()
    for start in range(0, len(files), 200):
        output = _git(
            root,
            "log",
            "--format=%H%x01%B%x00",
            f"{baseline}..HEAD",
            "--",
            *files[start : start + 200],
        )
        for entry in output.split("\x00"):
            sha, _, message = entry.strip().partition("\x01")
            if not sha:
                continue
            commits.add(sha)
            if any(pattern.search(message) for pattern in patterns):
                agent.add(sha)
    return len(commits), len(agent)


def module_statuses(root: Path, config: Config) -> list[ModuleStatus]:
    patterns = [re.compile(p) for p in config.visibility.agent_trailers]
    statuses = []
    for module_id, module in sorted(config.modules.items()):
        note_rel = f"{config.project.kb_dir}/modules/{module_id}.md"
        try:
            note = parse_note((root / note_rel).read_text(encoding="utf-8"))
            note_status = str(note.meta.get("status", "unknown"))
        except (OSError, NoteInvalid):
            statuses.append(ModuleStatus(module_id, "missing", never_reviewed=True))
            continue
        baseline = _reviewed_baseline(root, note_rel)
        if baseline is None:
            statuses.append(ModuleStatus(module_id, note_status, never_reviewed=True))
            continue
        sha, by, at = baseline
        files = _touched_files(root, sha, module.sources, config.structure.ignore)
        commits, agent = _commit_stats(root, sha, files, patterns) if files else (0, 0)
        lines = _lines_changed(root, sha, files) if files else 0
        statuses.append(
            ModuleStatus(module_id, note_status, False, by, at, sha, commits, lines, agent)
        )
    statuses.sort(key=lambda s: (not s.never_reviewed, -s.lines_changed_since, s.module_id))
    return statuses
