"""`milepost review` (SPEC sections 4.1 and 8)."""

import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from milepost.config import Config
from milepost.core.notes import Note, note_path_for_id, read_note, write_note
from milepost.errors import EnvironmentProblem, MilepostError, NoteInvalid, UsageError
from milepost.services.staleness import Staleness, module_staleness


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


def module_states(root: Path, config: Config) -> dict[str, Staleness]:
    """Staleness of every module, or nothing when git history cannot be read."""
    try:
        return dict(module_staleness(root, config))
    except UsageError:
        return {}


def draft_note_ids(root: Path, config: Config) -> list[str]:
    """Ids of the notes still waiting for a person (status: draft), in module order."""
    ids = []
    for module_id in sorted(config.modules):
        note_id = f"module/{module_id}"
        path = note_path_for_id(root / config.project.kb_dir, note_id)
        if path is None or not path.is_file():
            continue
        try:
            if read_note(path).meta.get("status") == "draft":
                ids.append(note_id)
        except NoteInvalid:
            continue
    return ids


def review_note(
    root: Path,
    config: Config,
    note_id: str,
    now: str,
    identity: Callable[[Path], str] = git_identity,
    states: Mapping[str, Staleness] | None = None,
) -> None:
    """Mark a note reviewed by the person running the command. `states` lets a caller that
    reviews many notes compute staleness once."""
    path, note = _load(root, config, note_id)
    module_id = note_id.partition("/")[2]
    if module_id in config.modules:
        state = (states if states is not None else module_states(root, config)).get(module_id)
        if state is not None and state.stale:
            raise MilepostError(
                f"note '{note_id}' is stale ({state.reason}). Update it first, then review it"
            )
    reviewer = identity(root)
    note.meta["status"] = "reviewed"
    note.meta["reviewed_by"] = reviewer
    note.meta["reviewed_at"] = now
    write_note(note, path)
