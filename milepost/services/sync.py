"""`milepost sync`: what changed and which notes to update, and how (SPEC section 8.3).

Rule-based and deterministic: no model is involved.
"""

from dataclasses import dataclass, field
from pathlib import Path

from milepost.config import Config
from milepost.core.citations import citing_changed
from milepost.core.glob import expand_sources, matches_any
from milepost.core.hashing import compute_source_hash
from milepost.core.notes import Note, parse_note
from milepost.errors import NoteInvalid, UsageError
from milepost.services.gitinfo import Changes, changed_files, working_tree_changes
from milepost.services.staleness import module_staleness


@dataclass
class NoteRef:
    id: str
    stale: bool
    source_hash_now: str


@dataclass
class FileChange:
    path: str
    status: str
    modules: list[str] = field(default_factory=list)
    notes: list[NoteRef] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)


@dataclass
class CitedBullet:
    note_id: str
    section: str
    text: str
    path: str


@dataclass
class SyncResult:
    changes: list[FileChange] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)
    verify: dict[str, list[str]] = field(default_factory=dict)
    cited: list[CitedBullet] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


def _load_notes(root: Path, config: Config) -> dict[str, Note]:
    """module id -> parsed note, for modules whose note file exists and is valid."""
    loaded = {}
    for module_id in config.modules:
        path = root / config.project.kb_dir / "modules" / f"{module_id}.md"
        if path.is_file():
            try:
                loaded[module_id] = parse_note(path.read_text(encoding="utf-8"))
            except NoteInvalid:
                continue
    return loaded


def _status_of(path: str, changes: Changes) -> str:
    if path in changes.deleted:
        return "deleted"
    return "added" if path in changes.added else "modified"


def _route(status: str, module_id: str, path: str) -> str:
    note_id = f"module/{module_id}"
    if status == "added":
        return f"{note_id}: add {path} to the File map (and Entry points if it is a new start)"
    if status == "deleted":
        return f"{note_id}: remove or rename {path} in the File map"
    return (
        f"{note_id}: re-read {path}; edit Purpose, File map, Invariants or Gotchas if the change "
        "affects them, otherwise kb_update with the unchanged body to confirm it still holds"
    )


def _cited_for(
    root: Path, config: Config, module_id: str, note: Note, changed: set[str]
) -> list[CitedBullet]:
    sources = config.modules[module_id].sources
    candidates = set(expand_sources(root, sources, []))
    candidates |= {p for p in changed if matches_any(p, sources)}
    return [
        CitedBullet(f"module/{module_id}", bullet.section, bullet.text, path)
        for bullet, path in citing_changed(note.body, candidates, changed)
    ]


def _stale_modules(root: Path, config: Config) -> set[str]:
    try:
        return {m for m, state in module_staleness(root, config).items() if state.stale}
    except UsageError:
        return set()


def sync(root: Path, config: Config, base: str | None = None) -> SyncResult:
    changes = changed_files(root, base) if base else working_tree_changes(root)
    kb_prefix = config.project.kb_dir.rstrip("/") + "/"
    ignore = config.structure.ignore
    paths = sorted(
        p for p in changes.all if not p.startswith(kb_prefix) and not matches_any(p, ignore)
    )
    result = SyncResult()
    if not paths:
        result.next_steps = ["No changed files; nothing to update."]
        return result

    if not config.modules and not (root / config.project.kb_dir / "modules").is_dir():
        # No knowledge base at all (typically no milepost.toml): report the changes and stop.
        result.changes = [FileChange(path, _status_of(path, changes)) for path in paths]
        result.next_steps = [
            f"{len(paths)} changed file(s). No knowledge base is set up in this repository, so "
            "there are no notes to update; the user can run /kb-init to start keeping notes"
        ]
        return result

    notes = _load_notes(root, config)
    stale = _stale_modules(root, config)
    hashes: dict[str, str] = {}
    affected: dict[str, list[str]] = {}
    missing_notes: dict[str, str] = {}
    changed = set(paths)
    for path in paths:
        status = _status_of(path, changes)
        modules = [
            m for m in sorted(config.modules) if matches_any(path, config.modules[m].sources)
        ]
        change = FileChange(path, status, modules)
        for module_id in modules:
            if module_id in notes:
                if module_id not in hashes:
                    sources = config.modules[module_id].sources
                    hashes[module_id] = compute_source_hash(
                        root, sources, config.structure.ignore
                    ).value
                change.notes.append(
                    NoteRef(f"module/{module_id}", module_id in stale, hashes[module_id])
                )
                route = _route(status, module_id, path)
                change.routes.append(route)
                affected.setdefault(module_id, []).append(route)
            elif not (root / config.project.kb_dir / "modules" / f"{module_id}.md").exists():
                text = f"module/{module_id} has no note yet: draft it (kb_draft_module)"
                change.routes.append(text)
                missing_notes.setdefault(module_id, text)
        if not modules:
            result.uncovered.append(path)
            change.routes.append(
                f"{path}: no module covers it (UNCOVERED_DIR); declare a module or ask the user"
            )
        result.changes.append(change)

    for module_id in sorted(affected):
        result.cited.extend(_cited_for(root, config, module_id, notes[module_id], changed))
    verify_modules = {m for change in result.changes for m in change.modules}
    result.verify = {
        m: config.modules[m].verify for m in sorted(verify_modules) if config.modules[m].verify
    }
    result.next_steps = _next_steps(result, affected, missing_notes)
    return result


def _next_steps(
    result: SyncResult, affected: dict[str, list[str]], missing_notes: dict[str, str]
) -> list[str]:
    steps = [f"update {route}" for _, routes in sorted(affected.items()) for route in routes]
    steps += [text for _, text in sorted(missing_notes.items())]
    steps += [
        f"confirm this still holds in {c.note_id} ({c.section}), {c.path} changed: {c.text}"
        for c in result.cited
    ]
    steps += [
        f"{path} is covered by no module: declare one or ask the user" for path in result.uncovered
    ]
    for module_id, commands in result.verify.items():
        steps += [f"run ({module_id}): {command}" for command in commands]
    steps.append("then call kb_check")
    return steps
