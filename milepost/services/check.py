"""`milepost check`: validate notes and detect staleness (SPEC section 6)."""

from dataclasses import dataclass, replace
from pathlib import Path

from wcmatch import glob

from milepost.config import Config
from milepost.core.findings import Finding
from milepost.core.glob import FLAGS
from milepost.core.hashing import compute_source_hash
from milepost.core.notes import Note, parse_note, validate_note
from milepost.errors import NoteInvalid
from milepost.services.coverage import uncovered_candidates
from milepost.services.gitinfo import Changes, changed_files, files_at, read_waivers
from milepost.services.render import render_index
from milepost.structure.candidates import Candidate

NOTE_DIRS = ("modules", "files", "passages")
WAIVABLE = {"STALE_NOTE", "ORPHAN_NOTE", "UNCOVERED_DIR"}


@dataclass
class CheckResult:
    findings: list[Finding]
    fail_on: str

    @property
    def exit_code(self) -> int:
        failed = any(finding.severity == "failure" for finding in self.findings)
        return 1 if failed and self.fail_on == "stale" else 0


@dataclass
class _LoadedNote:
    rel_path: str
    note: Note
    sources: list[str]


def _matches_any(path: str, patterns: list[str]) -> bool:
    return bool(patterns) and bool(glob.globmatch(path, patterns, flags=FLAGS))


def _load_notes(root: Path, config: Config, findings: list[Finding]) -> list[_LoadedNote]:
    kb_dir = config.project.kb_dir
    loaded = []
    for sub in NOTE_DIRS:
        for path in sorted((root / kb_dir / sub).rglob("*.md")):
            rel = path.relative_to(root / kb_dir).as_posix()
            full = f"{kb_dir}/{rel}"
            try:
                note = parse_note(path.read_text(encoding="utf-8"))
            except NoteInvalid as error:
                findings.append(Finding("failure", "NOTE_INVALID", full, str(error)))
                continue
            findings.extend(replace(f, path=full) for f in validate_note(note, rel))
            sources = note.meta.get("sources")
            loaded.append(
                _LoadedNote(
                    full, note, [str(s) for s in sources] if isinstance(sources, list) else []
                )
            )
    return loaded


def _check_staleness(
    root: Path, config: Config, notes: list[_LoadedNote], findings: list[Finding]
) -> None:
    for loaded in notes:
        meta = loaded.note.meta
        level, recorded = meta.get("level"), meta.get("source_hash")
        if level not in ("L2", "L3") or not recorded or recorded == "CONFLICT":
            continue
        note_id = str(meta.get("id"))
        result = compute_source_hash(root, loaded.sources, config.structure.ignore)
        if result.value != recorded:
            findings.append(
                Finding(
                    "failure",
                    "STALE_NOTE",
                    loaded.rel_path,
                    "source files changed since the note was written; re-read them and call "
                    f"kb_update, or run `milepost rehash {note_id}` after review",
                    note_id,
                )
            )
        if not result.manifest:
            if level == "L3":
                findings.append(
                    Finding(
                        "warning",
                        "ORPHAN_NOTE",
                        loaded.rel_path,
                        "the file this note describes no longer exists; delete or replace the note",
                        note_id,
                    )
                )
            else:
                findings.append(
                    Finding(
                        "warning", "EMPTY_SOURCE_SET", loaded.rel_path, result.warnings[0], note_id
                    )
                )


def _check_modules_and_index(root: Path, config: Config, findings: list[Finding]) -> None:
    kb_dir = config.project.kb_dir
    for module_id in config.modules:
        rel = f"{kb_dir}/modules/{module_id}.md"
        if not (root / rel).is_file():
            findings.append(
                Finding(
                    "warning",
                    "MISSING_NOTE",
                    rel,
                    f"module '{module_id}' has no note; run `milepost draft {module_id}`",
                    f"module/{module_id}",
                )
            )
    index_path = root / kb_dir / "INDEX.md"
    index_rel = f"{kb_dir}/INDEX.md"
    fresh = render_index(root, config)
    if not index_path.is_file():
        findings.append(
            Finding(
                "failure", "INDEX_DRIFT", index_rel, "INDEX.md is missing; run `milepost index`"
            )
        )
    elif index_path.read_text(encoding="utf-8") != fresh:
        findings.append(
            Finding(
                "failure",
                "INDEX_DRIFT",
                index_rel,
                "INDEX.md differs from a fresh render; run `milepost index`",
            )
        )


def _check_coverage(root: Path, config: Config, findings: list[Finding]) -> list[Candidate]:
    uncovered = uncovered_candidates(root, config.structure, config.modules)
    for candidate in uncovered:
        findings.append(
            Finding(
                "warning",
                "UNCOVERED_DIR",
                candidate.path,
                f"{candidate.path} is under a source root but no module covers it; "
                "see `milepost scan` to declare one",
                f"dir:{candidate.path}",
            )
        )
    return uncovered


def _check_detail_count(config: Config, notes: list[_LoadedNote], findings: list[Finding]) -> None:
    count = sum(1 for loaded in notes if loaded.note.meta.get("level") in ("L3", "L4"))
    if count > config.check.max_detail_notes:
        findings.append(
            Finding(
                "warning",
                "DETAIL_NOTE_COUNT",
                config.project.kb_dir,
                f"{count} L3/L4 notes exceed check.max_detail_notes "
                f"({config.check.max_detail_notes}); prefer updating module notes",
            )
        )


def _apply_ci_scope(
    root: Path,
    base: str,
    config: Config,
    findings: list[Finding],
    notes: list[_LoadedNote],
    uncovered: list[Candidate],
) -> list[Finding]:
    """Make failures depend on the change range, then apply waiver trailers."""
    waivers = read_waivers(root, base)
    changes: Changes = changed_files(root, base)
    ignore = config.structure.ignore
    sources_by_id = {str(n.note.meta.get("id")): n.sources for n in notes}
    new_dirs = {
        f"dir:{c.path}"
        for c in uncovered
        if not any(_matches_any(path, c.sources) for path in files_at(root, base, c.path))
    }

    def touches(patterns: list[str], paths: set[str]) -> bool:
        return any(_matches_any(p, patterns) and not _matches_any(p, ignore) for p in paths)

    scoped = []
    for finding in findings:
        failing = finding.severity == "failure"
        if finding.code == "STALE_NOTE":
            failing = touches(sources_by_id.get(finding.subject, []), changes.all)
        elif finding.code == "ORPHAN_NOTE":
            failing = touches(sources_by_id.get(finding.subject, []), changes.deleted)
        elif finding.code == "UNCOVERED_DIR":
            failing = finding.subject in new_dirs
        if finding.code in WAIVABLE:
            finding = replace(finding, severity="failure" if failing else "warning")
            if failing and finding.subject in waivers:
                reason = waivers[finding.subject]
                finding = replace(
                    finding, severity="warning", message=f"{finding.message} (waived: {reason})"
                )
        scoped.append(finding)
    return scoped


def run_check(root: Path, config: Config, base: str | None = None) -> CheckResult:
    findings: list[Finding] = []
    notes = _load_notes(root, config, findings)
    _check_staleness(root, config, notes, findings)
    _check_modules_and_index(root, config, findings)
    uncovered = _check_coverage(root, config, findings)
    _check_detail_count(config, notes, findings)
    if base is not None:
        findings = _apply_ci_scope(root, base, config, findings, notes, uncovered)
    findings.sort(key=lambda f: (f.path, f.code, f.subject, f.message))
    return CheckResult(findings=findings, fail_on=config.check.fail_on)
