"""`milepost review` and `milepost rehash` (SPEC sections 4.1 and 8)."""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from milepost.config import Config
from milepost.core.hashing import compute_source_hash
from milepost.core.notes import HASHED_LEVELS, Note, note_path_for_id, read_note, write_note
from milepost.errors import EnvironmentProblem, MilepostError, NoteInvalid, UsageError
from milepost.services.render import render_index


def git_identity(root: Path) -> str:
    """`Name <email>` from git config, or EnvironmentProblem if either is missing."""

    def setting(key: str) -> str:
        done = subprocess.run(
            ["git", "config", key], cwd=root, capture_output=True, text=True, check=False
        )
        return done.stdout.strip()

    name, email = setting("user.name"), setting("user.email")
    if not name or not email:
        raise EnvironmentProblem(
            "git identity is not set; run `git config user.name` and `git config user.email`"
        )
    return f"{name} <{email}>"


def _load(root: Path, config: Config, note_id: str) -> tuple[Path, Note]:
    path = note_path_for_id(root / config.project.kb_dir, note_id)
    if path is None or not path.is_file():
        raise UsageError(f"no note with id '{note_id}'")
    try:
        return path, read_note(path)
    except NoteInvalid as error:
        raise UsageError(f"note '{note_id}' is not valid: {error}") from error


def _hashed_sources(note: Note, note_id: str) -> list[str]:
    sources = note.meta.get("sources")
    if note.meta.get("level") not in HASHED_LEVELS or not isinstance(sources, list):
        raise UsageError(f"note '{note_id}' has no source set, so it has no hash")
    return [str(source) for source in sources]


def review_note(
    root: Path,
    config: Config,
    note_id: str,
    now: str,
    identity: Callable[[Path], str] = git_identity,
) -> None:
    """Mark a note reviewed by the person running the command. The source hash is not touched."""
    path, note = _load(root, config, note_id)
    recorded = note.meta.get("source_hash")
    if recorded == "CONFLICT":
        raise MilepostError(
            f"note '{note_id}' has a CONFLICT hash; read the merged prose, fix it, then run "
            f"`milepost rehash {note_id}` before reviewing"
        )
    if note.meta.get("level") in HASHED_LEVELS:
        current = compute_source_hash(
            root, _hashed_sources(note, note_id), config.structure.ignore
        ).value
        if current != recorded:
            raise MilepostError(
                f"note '{note_id}' is stale: its sources changed since it was written. "
                "Update the note first, then review it"
            )
    reviewer = identity(root)
    note.meta["status"] = "reviewed"
    note.meta["reviewed_by"] = reviewer
    note.meta["reviewed_at"] = now
    write_note(note, path)
    (root / config.project.kb_dir / "INDEX.md").write_text(render_index(root, config))


@dataclass
class RehashResult:
    old_hash: str
    new_hash: str
    manifest: dict[str, str] = field(default_factory=dict)


def plan_rehash(root: Path, config: Config, note_id: str) -> RehashResult:
    """What a rehash would write, without writing it."""
    _, note = _load(root, config, note_id)
    result = compute_source_hash(root, _hashed_sources(note, note_id), config.structure.ignore)
    return RehashResult(str(note.meta.get("source_hash", "")), result.value, result.manifest)


def rehash_note(root: Path, config: Config, note_id: str) -> RehashResult:
    """Record the current source hash on a note whose prose a person has just read."""
    path, note = _load(root, config, note_id)
    plan = plan_rehash(root, config, note_id)
    note.meta["source_hash"] = plan.new_hash
    write_note(note, path)
    return plan
