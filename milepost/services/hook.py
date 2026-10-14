"""Entry points for the Claude Code plugin hooks (SPEC section 12.4).

Each function takes the hook's JSON input and returns the JSON to print, or "" for no output.
They never raise for ordinary problems: a hook that fails must not get in the agent's way.
"""

import json
import os
from pathlib import Path
from typing import Any

from milepost.config import Config, load_config
from milepost.core.glob import matches_any
from milepost.errors import MilepostError
from milepost.services.check import run_check
from milepost.services.coverage import CONFIG_NAME, uncovered_candidates
from milepost.services.gitinfo import changed_in_head, working_tree_changes
from milepost.services.kb import KbToolError, kb_file, kb_overview

INDEX_CHARS = 3000
MAX_REASON_FINDINGS = 10
REMINDER = (
    "Before searching code: call kb_module for the module that owns your task, kb_outline for "
    "the files you will read, and kb_impact for the files you will change. After a change: "
    "kb_sync, kb_update each listed note, then kb_check."
)


def project_root(payload: dict[str, Any], env_dir: str | None) -> Path:
    """The repository to act on: CLAUDE_PROJECT_DIR (stable even if the agent runs `cd`), else
    the hook's cwd, else the process cwd, walking up to the nearest milepost.toml."""
    start = Path(str(env_dir or payload.get("cwd") or Path.cwd()))
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
    raw = None
    if isinstance(tool_input, dict):
        raw = tool_input.get("file_path") or tool_input.get("notebook_path")
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
        if relative.startswith(os.path.normpath(config.project.kb_dir).replace(os.sep, "/") + "/"):
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
        matching = [
            c
            for c in uncovered_candidates(root, config.structure, config.modules)
            if c.path and relative.startswith(c.path.rstrip("/") + "/")
        ]
        if matching:
            directory = max(matching, key=lambda c: len(c.path)).path
            text = (
                f"{relative} is in {directory}, which no module covers (UNCOVERED_DIR). If it "
                "should have a note, declare a module in milepost.toml and call "
                "kb_draft_module; otherwise ask the user."
            )
            return _context("PostToolUse", text)
    except (MilepostError, OSError, KbToolError):
        return ""
    return ""


def _module_sources(config: Config, finding_path: str) -> list[str]:
    """Source globs of the module whose note file is `finding_path`."""
    kb = config.project.kb_dir
    for module_id, module in config.modules.items():
        if finding_path == f"{kb}/modules/{module_id}.md":
            return module.sources
    return []


def stop(root: Path, payload: dict[str, Any]) -> str:
    """Block once when a note is stale for files changed in this piece of work.

    "Changed" means the working tree against HEAD plus the latest commit, so an agent that
    commits before finishing is still caught. Old debt is left to `check`, pre-commit and CI."""
    if payload.get("stop_hook_active"):
        return ""
    try:
        config = load_config(root / CONFIG_NAME)
        findings = run_check(root, config, with_churn=False).findings
        changed = {
            path
            for path in working_tree_changes(root).all | changed_in_head(root)
            if not matches_any(path, config.structure.ignore)
        }
    except (MilepostError, OSError):
        return ""
    relevant = [
        f
        for f in findings
        if f.code == "STALE_NOTE"
        and any(matches_any(path, _module_sources(config, f.path)) for path in changed)
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
