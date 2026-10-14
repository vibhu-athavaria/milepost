"""Deterministic rendering of the L1 module index, built on demand (SPEC section 8.2)."""

from pathlib import Path

from milepost.config import Config
from milepost.core.notes import purpose_line, read_note
from milepost.errors import NoteInvalid


def _module_row(note_path: Path) -> tuple[str, str]:
    """(purpose, status) for a module note file."""
    if not note_path.is_file():
        return "(no note yet)", "missing"
    try:
        note = read_note(note_path)
    except NoteInvalid:
        return "(invalid note)", "invalid"
    purpose = purpose_line(note.body) or "(no Purpose section)"
    return purpose, str(note.meta.get("status", "unknown"))


def render_index(root: Path, config: Config) -> str:
    kb_dir = config.project.kb_dir
    lines = ["# Codebase index", "", "| Module | Purpose | Status | Note |", "|---|---|---|---|"]
    for module_id in sorted(config.modules):
        note_rel = f"{kb_dir}/modules/{module_id}.md"
        purpose, status = _module_row(root / note_rel)
        lines.append(f"| {module_id} | {purpose} | {status} | {note_rel} |")
    return "\n".join(lines) + "\n"
