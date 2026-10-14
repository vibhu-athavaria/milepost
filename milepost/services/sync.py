"""`milepost sync`: what changed and which notes to update, and how (SPEC section 8.3).

Rule-based and deterministic: no model is involved.
"""

from dataclasses import dataclass, field
from pathlib import Path

from milepost.config import Config
from milepost.core.citations import citing_changed
from milepost.core.glob import expand_sources, matches_any
from milepost.core.hashing import compute_source_hash
from milepost.core.notes import HASHED_LEVELS, Note, parse_note
from milepost.errors import NoteInvalid
from milepost.services.gitinfo import Changes, changed_files, working_tree_changes


@dataclass
class NoteRef:
    id: str
    level: str
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


@dataclass
class _KbNote:
    id: str
    level: str
    note: Note
    sources: list[str]
    recorded: str
    module_id: str | None


def _load_kb_notes(root: Path, config: Config) -> list[_KbNote]:
    kb = root / config.project.kb_dir
    paths = [kb / "modules" / f"{m}.md" for m in sorted(config.modules)]
    paths += sorted((kb / "files").rglob("*.md")) if (kb / "files").is_dir() else []
    loaded = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            note = parse_note(path.read_text(encoding="utf-8"))
        except NoteInvalid:
            continue
        sources = note.meta.get("sources")
        if note.meta.get("level") not in HASHED_LEVELS or not isinstance(sources, list):
            continue
        module_id = path.stem if path.parent.name == "modules" else None
        loaded.append(
            _KbNote(
                str(note.meta.get("id")),
                str(note.meta.get("level")),
                note,
                [str(s) for s in sources],
                str(note.meta.get("source_hash", "")),
                module_id,
            )
        )
    return loaded


def _status_of(path: str, changes: Changes) -> str:
    if path in changes.deleted:
        return "deleted"
    return "added" if path in changes.added else "modified"


def _route(status: str, note: _KbNote, path: str) -> str:
    if note.level == "L3":
        if status == "deleted":
            return f"{note.id}: ORPHAN_NOTE, {path} is gone; tell the user, do not delete the note"
        return f"{note.id}: re-read {path}; edit the note if the change affects it, else refresh it"
    if status == "added":
        return f"{note.id}: add {path} to the File map (and Entry points if it is a new start)"
    if status == "deleted":
        return f"{note.id}: remove or rename {path} in the File map"
    return (
        f"{note.id}: re-read {path}; edit Purpose, File map, Invariants or Gotchas if the "
        "change affects them, otherwise kb_update with the unchanged body to refresh the hash"
    )


def _cited_for(root: Path, config: Config, note: _KbNote, changed: set[str]) -> list[CitedBullet]:
    if note.module_id is None:
        return []
    sources = config.modules[note.module_id].sources
    candidates = set(expand_sources(root, sources, []))
    candidates |= {p for p in changed if matches_any(p, sources)}
    return [
        CitedBullet(note.id, bullet.section, bullet.text, path)
        for bullet, path in citing_changed(note.note.body, candidates, changed)
    ]


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

    kb_notes = _load_kb_notes(root, config)
    hash_cache: dict[str, str] = {}
    affected: dict[str, list[str]] = {}
    verify_modules: set[str] = set()
    missing_notes: dict[str, str] = {}
    changed = set(paths)
    for path in paths:
        status = _status_of(path, changes)
        modules = [
            m for m in sorted(config.modules) if matches_any(path, config.modules[m].sources)
        ]
        change = FileChange(path, status, modules)
        for note in kb_notes:
            covers = (
                note.module_id in modules if note.module_id else matches_any(path, note.sources)
            )
            if not covers:
                continue
            if note.id not in hash_cache:
                hash_cache[note.id] = compute_source_hash(
                    root, note.sources, config.structure.ignore
                ).value
            now = hash_cache[note.id]
            change.notes.append(NoteRef(note.id, note.level, now != note.recorded, now))
            route = _route(status, note, path)
            change.routes.append(route)
            affected.setdefault(note.id, []).append(route)
        for module_id in modules:
            verify_modules.add(module_id)
            note_file = root / config.project.kb_dir / "modules" / f"{module_id}.md"
            if not note_file.exists():
                text = f"module/{module_id} has no note yet: draft it (kb_draft_module)"
                change.routes.append(text)
                missing_notes.setdefault(module_id, text)
        if not modules:
            result.uncovered.append(path)
            change.routes.append(
                f"{path}: no module covers it (UNCOVERED_DIR); declare a module or ask the user"
            )
        result.changes.append(change)

    for note in kb_notes:
        if note.id in affected:
            result.cited.extend(_cited_for(root, config, note, changed))
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
