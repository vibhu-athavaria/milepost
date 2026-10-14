"""The logic behind each MCP tool (SPEC section 11). Pure functions: the server only wires them.

Every function returns a plain dict that ends with `next_steps`, a list of short instructions
computed from repository state (never by a model). Failures raise KbToolError with one of the
codes NOT_FOUND, INVALID_INPUT, CONFLICT, STALE_READ, ENVIRONMENT.
"""

import functools
import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milepost.config import Config, load_config, resolve_model
from milepost.core.glob import matches_any
from milepost.core.hashing import compute_source_hash
from milepost.core.notes import (
    HASHED_LEVELS,
    Note,
    note_path_for_id,
    parse_note,
    write_note,
)
from milepost.embeddings import Embedder
from milepost.errors import (
    ConfigNotFound,
    EnvironmentProblem,
    IndexMissing,
    IndexRebuildRequired,
    MilepostError,
    NoteInvalid,
    NotFoundError,
    ProviderError,
    SecretDetected,
    UsageError,
)
from milepost.llm.client import LlmClient
from milepost.services.check import run_check
from milepost.services.coverage import CONFIG_NAME
from milepost.services.draft import draft_modules
from milepost.services.impact import file_impact
from milepost.services.index import run_index
from milepost.services.outline import outline_file
from milepost.services.render import render_index
from milepost.services.search import search as run_search
from milepost.services.sync import sync as run_sync

MAX_BODY_CHARS = 20_000
MAX_SEARCH_RESULTS = 10
LEVEL_BY_PREFIX = {"module": "L2", "file": "L3", "passage": "L4"}


class KbToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _tool[**P](func: Callable[P, dict[str, Any]]) -> Callable[P, dict[str, Any]]:
    """Turn any MilepostError a tool raises into a KbToolError with a documented code."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except MilepostError as error:
            raise _translate(error) from error

    return wrapper


def _config(root: Path) -> Config:
    try:
        return load_config(root / CONFIG_NAME)
    except ConfigNotFound as error:
        raise KbToolError(
            "ENVIRONMENT", "no milepost.toml in this repository; the user can run /kb-init"
        ) from error
    except MilepostError as error:
        raise KbToolError("ENVIRONMENT", str(error)) from error


def _translate(error: MilepostError) -> KbToolError:
    if isinstance(error, NotFoundError):
        return KbToolError("NOT_FOUND", str(error))
    if isinstance(error, SecretDetected | UsageError):
        return KbToolError("INVALID_INPUT", str(error))
    return KbToolError("ENVIRONMENT", str(error))


def _read(path: Path) -> Note | None:
    try:
        return parse_note(path.read_text(encoding="utf-8"))
    except (OSError, NoteInvalid):
        return None


def _hash_now(root: Path, config: Config, sources: list[str]) -> str:
    return compute_source_hash(root, sources, config.structure.ignore).value


def _note_sources(note: Note) -> list[str]:
    sources = note.meta.get("sources")
    return [str(s) for s in sources] if isinstance(sources, list) else []


def _branch(root: Path) -> str:
    try:
        done = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return "(git not installed)"
    return done.stdout.strip() or "(detached HEAD or not a git repository)"


def _repo_relative(root: Path, path: str) -> str:
    """Repo-relative POSIX path, rejecting absolute paths and any that leave the repository."""
    normal = os.path.normpath(path).replace(os.sep, "/")
    if normal.startswith(("/", "../")) or normal == ".." or Path(path).is_absolute():
        raise KbToolError("INVALID_INPUT", f"{path} is outside the repository")
    return normal


def _write_index_md(root: Path, config: Config) -> None:
    index_path = root / config.project.kb_dir / "INDEX.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(render_index(root, config), encoding="utf-8")


def _note_summary(root: Path, config: Config, note_id: str, note: Note) -> dict[str, Any]:
    sources = _note_sources(note)
    now = _hash_now(root, config, sources) if sources else ""
    recorded = str(note.meta.get("source_hash", ""))
    return {
        "id": note_id,
        "level": note.meta.get("level"),
        "status": note.meta.get("status"),
        "stale": bool(sources) and now != recorded,
        "source_hash_now": now,
    }


def _status_steps(summary: dict[str, Any]) -> list[str]:
    steps = []
    if summary["status"] == "draft":
        steps.append(
            f"{summary['id']} is a draft: verify its claims in the source and tell the user "
            "if you relied on it"
        )
    if summary["stale"]:
        steps.append(
            f"{summary['id']} is stale: re-read the sources, then kb_update it with "
            "read_hash=source_hash_now"
        )
    return steps


@_tool
def kb_overview(root: Path) -> dict[str, Any]:
    config = _config(root)
    index_path = root / config.project.kb_dir / "INDEX.md"
    if not index_path.is_file():
        raise KbToolError("NOT_FOUND", "no knowledge base yet; the user can run /kb-init")
    index = index_path.read_text(encoding="utf-8")
    findings = run_check(root, config, with_churn=False).findings
    stale = sum(1 for f in findings if f.code == "STALE_NOTE")
    drafts = 0
    for module_id in config.modules:
        note = _read(root / config.project.kb_dir / "modules" / f"{module_id}.md")
        drafts += 1 if note is not None and note.meta.get("status") == "draft" else 0
    steps = ["call kb_module for the module that owns your task; do not grep the repo first"]
    if stale:
        steps.append(f"{stale} note(s) are stale: kb_check lists them; do not trust a stale note")
    return {
        "index": index[:MAX_BODY_CHARS],
        "truncated": len(index) > MAX_BODY_CHARS,
        "stale_count": stale,
        "draft_count": drafts,
        "branch": _branch(root),
        "next_steps": steps,
    }


@_tool
def kb_module(root: Path, module_id: str) -> dict[str, Any]:
    config = _config(root)
    module = config.modules.get(module_id)
    note_path = root / config.project.kb_dir / "modules" / f"{module_id}.md"
    if module is None:
        raise KbToolError("NOT_FOUND", f"module '{module_id}' is not declared in milepost.toml")
    note = _read(note_path) if note_path.is_file() else None
    if note is None:
        raise KbToolError(
            "NOT_FOUND", f"module '{module_id}' has no valid note; call kb_draft_module"
        )
    summary = _note_summary(root, config, f"module/{module_id}", note)
    related = []
    for other in module.related:
        other_note = _read(root / config.project.kb_dir / "modules" / f"{other}.md")
        related.append(
            {
                "id": f"module/{other}",
                "title": config.modules[other].title,
                "status": other_note.meta.get("status") if other_note else "missing",
            }
        )
    steps = _status_steps(summary)
    if len(note.body) > MAX_BODY_CHARS:
        steps.append(
            f"this note is over {MAX_BODY_CHARS} characters and kb_update will reject it as is; "
            "shorten it when you update it"
        )
    steps.append("call kb_outline on each file you will read, then read only those line ranges")
    steps.append("call kb_impact on each file you will change")
    return {
        **summary,
        "meta": note.meta,
        "body": note.body,
        "verify": module.verify,
        "related": related,
        "next_steps": steps,
    }


@_tool
def kb_file(root: Path, path: str) -> dict[str, Any]:
    config = _config(root)
    relative = _repo_relative(root, path)
    kb = root / config.project.kb_dir
    notes: list[dict[str, Any]] = []
    for module_id in sorted(config.modules):
        if matches_any(relative, config.modules[module_id].sources):
            note = _read(kb / "modules" / f"{module_id}.md")
            if note is not None:
                notes.append(_note_summary(root, config, f"module/{module_id}", note))
    l3 = _read(kb / "files" / f"{relative}.md")
    if l3 is not None:
        notes.append(_note_summary(root, config, f"file/{relative}", l3))
    steps: list[str] = []
    if notes:
        steps.append(f"after changing {relative}, call kb_sync and kb_update each listed note")
        for summary in notes:
            steps += _status_steps(summary)
    else:
        steps.append(f"no note covers {relative}: it may be UNCOVERED; call kb_check")
    absolute = root / relative
    return {
        "path": relative,
        "notes": notes,
        "covered": bool(notes),
        "file_hash_now": _hash_now(root, config, [relative]) if absolute.is_file() else "",
        "next_steps": steps,
    }


@_tool
def kb_search(
    root: Path,
    embedder_for: Callable[[Config], Embedder],
    query: str,
    level: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    config = _config(root)
    embedder = embedder_for(config)
    try:
        run_index(root, config, embedder)
        results = run_search(
            root, config, embedder, query, level=level, k=min(max(limit, 1), MAX_SEARCH_RESULTS)
        )
    except (IndexMissing, IndexRebuildRequired) as error:
        raise KbToolError("ENVIRONMENT", str(error)) from error
    except MilepostError as error:
        raise _translate(error) from error
    return {
        "results": [asdict(result) for result in results],
        "next_steps": ["call kb_module on the best result's module before reading code"],
    }


@_tool
def kb_check(root: Path) -> dict[str, Any]:
    config = _config(root)
    result = run_check(root, config)
    findings = [
        {"severity": f.severity, "code": f.code, "path": f.path, "message": f.message}
        for f in result.findings
    ]
    failures = sum(1 for f in result.findings if f.severity == "failure")
    steps = (
        ["fix every failure: update the stale notes with kb_update; never write a KB-Waive"]
        if failures
        else ["no failures"]
    )
    return {"ok": result.exit_code == 0, "findings": findings, "next_steps": steps}


@_tool
def kb_outline(root: Path, path: str) -> dict[str, Any]:
    try:
        result = outline_file(root, path)
    except MilepostError as error:
        raise _translate(error) from error
    return {
        **asdict(result),
        "next_steps": ["read only the line ranges you need, using offset and limit"],
    }


@_tool
def kb_impact(root: Path, path: str) -> dict[str, Any]:
    config = _config(root)
    try:
        result = file_impact(root, config, path)
    except MilepostError as error:
        raise _translate(error) from error
    steps = ["run the tests listed here after changing the file"] if result.tests else []
    steps += [f"run: {c}" for module in result.modules for c in module.verify]
    return {**asdict(result), "next_steps": steps}


@_tool
def kb_sync(root: Path, base: str | None = None) -> dict[str, Any]:
    config = _config(root)
    try:
        result = run_sync(root, config, base)
    except MilepostError as error:
        raise _translate(error) from error
    return {**asdict(result)}


@_tool
def kb_update(
    root: Path, note_id: str, body: str, read_hash: str | None, now: str
) -> dict[str, Any]:
    config = _config(root)
    prefix, _, name = note_id.partition("/")
    level = LEVEL_BY_PREFIX.get(prefix)
    kb = root / config.project.kb_dir
    path = note_path_for_id(kb, note_id)
    if level is None or path is None:
        raise KbToolError(
            "INVALID_INPUT", f"'{note_id}' is not a note id (module/, file/, passage/)"
        )
    if not name or ".." in Path(name).parts or Path(name).is_absolute():
        raise KbToolError("INVALID_INPUT", f"'{note_id}' must not contain '..' or start with '/'")
    if level == "L3":
        name = _repo_relative(root, name)
        path = note_path_for_id(kb, f"{prefix}/{name}")
    if path is None or not path.resolve().is_relative_to(kb.resolve()):
        raise KbToolError("INVALID_INPUT", f"'{note_id}' resolves outside the knowledge base")
    if len(body) > MAX_BODY_CHARS:
        raise KbToolError("INVALID_INPUT", f"body is {len(body)} characters; the limit is 20000")
    if not body.strip():
        raise KbToolError("INVALID_INPUT", "body is empty")
    existing = _read(path) if path.is_file() else None
    if path.is_file() and existing is None:
        raise KbToolError(
            "INVALID_INPUT",
            f"{note_id} exists but its file is not a valid note; ask the user to fix or "
            "remove it, do not overwrite it",
        )

    if level == "L2" and existing is None:
        raise KbToolError(
            "NOT_FOUND",
            f"{note_id} does not exist; new module notes come from kb_draft_module "
            "(declare the module in milepost.toml first)",
        )
    if level == "L3" and existing is None and not (root / name).is_file():
        raise KbToolError("NOT_FOUND", f"{name} is not a file in this repository")

    meta: dict[str, Any]
    if existing is not None:
        meta = dict(existing.meta)
    elif level == "L3":
        meta = {"kb_schema": 1, "id": note_id, "level": "L3", "title": name, "sources": [name]}
    else:
        meta = {"kb_schema": 1, "id": note_id, "level": "L4", "title": name}

    if level in HASHED_LEVELS:
        sources = _note_sources(Note(meta, ""))
        if not read_hash:
            raise KbToolError(
                "INVALID_INPUT",
                "read_hash is required for L2 and L3 notes: pass source_hash_now from "
                "kb_module or kb_file",
            )
        current = _hash_now(root, config, sources)
        if read_hash != current:
            raise KbToolError(
                "STALE_READ",
                "the sources changed after you read them; call kb_module or kb_file again, "
                "re-read the source, and retry",
            )
        meta["source_hash"] = current

    meta["status"] = "draft"
    meta["written_by"] = "agent"
    meta["written_at"] = now
    meta.pop("reviewed_by", None)
    meta.pop("reviewed_at", None)
    write_note(Note(meta=meta, body="\n" + body.strip("\n") + "\n"), path)
    _write_index_md(root, config)

    rel = f"{config.project.kb_dir}/{path.relative_to(kb).as_posix()}"
    findings = [
        {"severity": f.severity, "code": f.code, "message": f.message}
        for f in run_check(root, config, with_churn=False).findings
        if f.path == rel
    ]
    return {
        "id": note_id,
        "status": "draft",
        "source_hash": meta.get("source_hash", ""),
        "findings": findings,
        "next_steps": [
            f"tell the user {note_id} is now a draft and a person must run "
            f"`milepost review {note_id}`",
            "call kb_check before committing",
        ],
    }


@_tool
def kb_draft_module(
    root: Path,
    module_id: str,
    client: LlmClient,
    environ: Mapping[str, str],
    now: str,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    config = _config(root)
    if module_id not in config.modules:
        raise KbToolError(
            "NOT_FOUND",
            f"module '{module_id}' is not declared; add [modules.{module_id}] with sources "
            "to milepost.toml first",
        )
    note_path = root / config.project.kb_dir / "modules" / f"{module_id}.md"
    if note_path.exists():
        raise KbToolError(
            "CONFLICT", f"module/{module_id} already has a note; redrafting is a human action"
        )
    try:
        model = resolve_model(config, environ)
    except EnvironmentProblem as error:
        raise KbToolError("ENVIRONMENT", str(error)) from error
    try:
        draft_modules(root, config, [module_id], client, model, False, now, sleep)
    except ProviderError as error:
        raise _translate(error) from error
    _write_index_md(root, config)
    return {
        "id": f"module/{module_id}",
        "status": "draft",
        "next_steps": [
            f"ask a human to read the note and run `milepost review module/{module_id}`",
            "call kb_check",
        ],
    }
