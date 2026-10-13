"""Entry points for the Claude Code plugin hooks (SPEC section 12.4).

Each function takes the hook's JSON input and returns the JSON to print, or "" for no output.
They never raise for ordinary problems: a hook that fails must not get in the agent's way.
"""

import json
from pathlib import Path
from typing import Any

from milepost.config import load_config
from milepost.core.glob import matches_any
from milepost.errors import MilepostError
from milepost.services.check import run_check
from milepost.services.coverage import CONFIG_NAME, uncovered_candidates
from milepost.services.gitinfo import working_tree_changes
from milepost.services.kb import kb_file, kb_overview

INDEX_CHARS = 3000
MAX_REASON_FINDINGS = 10
REMINDER = (
    "Before searching code: call kb_module for the module that owns your task, kb_outline for "
    "the files you will read, and kb_impact for the files you will change. After a change: "
    "kb_sync, kb_update each listed note, then kb_check."
)


def project_root(payload: dict[str, Any], env_dir: str | None) -> Path:
    """The repository to act on: the hook's cwd, else CLAUDE_PROJECT_DIR, else the cwd of the
    process, walking up to the nearest milepost.toml."""
    start = Path(str(payload.get("cwd") or env_dir or Path.cwd()))
    for directory in (start, *start.parents):
        if (directory / CONFIG_NAME).is_file():
            return directory
    return start


def _context(event: str, text: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def session_start(root: Path) -> str:
    try:
        overview = kb_overview(root)
    except Exception:  # noqa: BLE001 - a hook must never fail the session
        return ""
    index = str(overview["index"])
    if len(index) > INDEX_CHARS:
        index = index[:INDEX_CHARS] + "\n(index cut; call kb_overview for all of it)"
    counts = f"{overview['stale_count']} stale note(s), {overview['draft_count']} draft note(s)."
    return _context("SessionStart", f"{index}\n{counts}\n{REMINDER}")


def _edited_path(root: Path, payload: dict[str, Any]) -> str | None:
    tool_input = payload.get("tool_input")
    raw = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    try:
        return (
            (path if path.is_absolute() else root / path)
            .resolve()
            .relative_to(root.resolve())
            .as_posix()
        )
    except ValueError:
        return None


def post_edit(root: Path, payload: dict[str, Any]) -> str:
    relative = _edited_path(root, payload)
    if relative is None:
        return ""
    try:
        config = load_config(root / CONFIG_NAME)
        if relative.startswith(config.project.kb_dir.rstrip("/") + "/"):
            return ""
        covered = kb_file(root, relative)
        lines = []
        for note in covered["notes"]:
            flags = [str(note["status"])] + (["STALE"] if note["stale"] else [])
            lines.append(f"- {note['id']} ({', '.join(flags)})")
        if lines:
            text = (
                f"You edited {relative}. Notes that describe it:\n"
                + "\n".join(lines)
                + "\nBefore you finish: call kb_sync and kb_update each of these notes."
            )
            return _context("PostToolUse", text)
        for candidate in uncovered_candidates(root, config.structure, config.modules):
            if relative.startswith(candidate.path + "/"):
                text = (
                    f"{relative} is in {candidate.path}, which no module covers "
                    "(UNCOVERED_DIR). If it should have a note, declare a module in "
                    "milepost.toml and call kb_draft_module; otherwise ask the user."
                )
                return _context("PostToolUse", text)
    except (MilepostError, OSError):
        return ""
    return ""


def stop(root: Path, payload: dict[str, Any]) -> str:
    if payload.get("stop_hook_active"):
        return ""
    try:
        config = load_config(root / CONFIG_NAME)
        findings = run_check(root, config).findings
        changed = working_tree_changes(root).all
    except (MilepostError, OSError):
        return ""
    module_sources = {
        f"{config.project.kb_dir}/modules/{module_id}.md": module.sources
        for module_id, module in config.modules.items()
    }
    relevant = [
        f
        for f in findings
        if f.severity == "failure"
        and (
            f.code != "STALE_NOTE"
            or any(matches_any(p, module_sources.get(f.path, [])) for p in changed)
            or f.path.startswith(f"{config.project.kb_dir}/files/")
        )
    ]
    if not relevant:
        return ""
    lines = [f"- {f.code} {f.path}: {f.message}" for f in relevant[:MAX_REASON_FINDINGS]]
    reason = (
        "The knowledge base is out of date for the files you changed:\n"
        + "\n".join(lines)
        + "\nCall kb_sync, kb_update each stale note (pass read_hash from kb_module), then "
        "kb_check. Do not write a KB-Waive; ask the user if you cannot fix a finding."
    )
    return json.dumps({"decision": "block", "reason": reason})
