"""Git merge driver for note files (SPEC section 10.3).

A merge never silently chooses a source hash: when both sides changed it, the result is the
sentinel CONFLICT, which `milepost check` rejects until a person runs `milepost rehash`.
"""

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from milepost.core.notes import Note, parse_note, render_note
from milepost.errors import MilepostError, NoteInvalid

_MISSING = object()
_REVIEW_KEYS = ("reviewed_by", "reviewed_at")


@dataclass
class MergeResult:
    text: str
    body_conflict: bool


def _merge_value(key: str, base: Any, ours: Any, theirs: Any) -> Any:
    if ours == theirs:
        return ours
    if ours == base:
        return theirs
    if theirs == base:
        return ours
    if key == "source_hash":
        return "CONFLICT"
    if key == "status":
        return "draft"
    return ours


def _merge_meta(
    base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any]
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in {*base, *ours, *theirs}:
        value = _merge_value(
            key, base.get(key, _MISSING), ours.get(key, _MISSING), theirs.get(key, _MISSING)
        )
        if value is not _MISSING:
            merged[key] = value
    return merged


def _review_still_valid(merged: dict[str, Any], body: str, notes: list[Note]) -> bool:
    """A review counts only for the exact prose the reviewer read: a merge that mixes in the
    other side's edits is unreviewed text, so the note goes back to draft."""
    base, ours, theirs = notes
    if body == base.body:
        return True
    return any(
        side.meta.get("status") == "reviewed"
        and side.body == body
        and side.meta.get("reviewed_at") == merged.get("reviewed_at")
        for side in (ours, theirs)
    )


def _git_merge_file(base: str, ours: str, theirs: str) -> tuple[str, bool]:
    with tempfile.TemporaryDirectory() as tmp:
        paths = {name: Path(tmp) / name for name in ("base", "ours", "theirs")}
        for name, text in (("base", base), ("ours", ours), ("theirs", theirs)):
            paths[name].write_text(text, encoding="utf-8")
        done = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                "-L",
                "ours",
                "-L",
                "base",
                "-L",
                "theirs",
                str(paths["ours"]),
                str(paths["base"]),
                str(paths["theirs"]),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    if done.returncode < 0 or done.returncode > 127:
        raise MilepostError(f"git merge-file failed: {done.stderr.strip()}")
    return done.stdout, done.returncode > 0


def merge_notes(base: str, ours: str, theirs: str) -> MergeResult:
    parsed: list[Note] = []
    try:
        parsed = [parse_note(text) for text in (base, ours, theirs)]
    except NoteInvalid:
        text, conflict = _git_merge_file(base, ours, theirs)
        return MergeResult(text, conflict)
    base_note, ours_note, theirs_note = parsed
    body, conflict = _git_merge_file(base_note.body, ours_note.body, theirs_note.body)
    meta = _merge_meta(base_note.meta, ours_note.meta, theirs_note.meta)
    if meta.get("status") == "reviewed" and not _review_still_valid(meta, body, parsed):
        meta["status"] = "draft"
    if meta.get("status") != "reviewed":
        for key in _REVIEW_KEYS:
            meta.pop(key, None)
    return MergeResult(render_note(Note(meta=meta, body=body)), conflict)


def run_merge_driver(base_path: Path, ours_path: Path, theirs_path: Path, name: str) -> int:
    """Write the merge into `ours_path`. Returns the exit code git expects (non-zero = conflict)."""
    if Path(name).name == "INDEX.md":
        return 0  # a leftover from an older version (the index is no longer stored): keep ours
    result = merge_notes(
        base_path.read_text(encoding="utf-8"),
        ours_path.read_text(encoding="utf-8"),
        theirs_path.read_text(encoding="utf-8"),
    )
    ours_path.write_text(result.text, encoding="utf-8")
    return 1 if result.body_conflict else 0
