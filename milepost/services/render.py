"""Deterministic rendering of kb/INDEX.md, the L1 index (SPEC section 8.2)."""

from pathlib import Path

from milepost.config import Config
from milepost.core.notes import read_note
from milepost.errors import NoteInvalid


def _module_status(note_path: Path) -> str:
    if not note_path.is_file():
        return "missing"
    try:
        return str(read_note(note_path).meta.get("status", "unknown"))
    except NoteInvalid:
        return "invalid"


def render_index(root: Path, config: Config) -> str:
    kb_dir = config.project.kb_dir
    lines = ["# Codebase index", "", "| Module | Title | Status | Note |", "|---|---|---|---|"]
    for module_id in sorted(config.modules):
        note_rel = f"{kb_dir}/modules/{module_id}.md"
        status = _module_status(root / note_rel)
        lines.append(f"| {module_id} | {config.modules[module_id].title} | {status} | {note_rel} |")
    return "\n".join(lines) + "\n"
