"""`milepost check`: validate notes and detect staleness (SPEC section 6)."""

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from wcmatch import glob

from milepost.config import Config
from milepost.core.citations import all_citations, path_matches
from milepost.core.findings import Finding
from milepost.core.glob import FLAGS, expand_sources
from milepost.core.notes import Note, parse_note, validate_note
from milepost.errors import NoteInvalid, UsageError
from milepost.services.coverage import uncovered_candidates
from milepost.services.gitinfo import Changes, changed_files, files_at, read_waivers, repo_files
from milepost.services.staleness import module_staleness
from milepost.services.status import module_statuses
from milepost.structure.candidates import Candidate

NOTE_DIRS = ("modules",)
WAIVABLE = {"STALE_NOTE", "UNCOVERED_DIR"}


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


def _stale_severity(config: Config) -> Literal["failure", "warning"]:
    return "failure" if config.check.stale == "fail" else "warning"


def _stale_finding(config: Config, module_id: str, reason: str) -> Finding:
    return Finding(
        _stale_severity(config),
        "STALE_NOTE",
        f"{config.project.kb_dir}/modules/{module_id}.md",
        f"{reason}; re-read the code and update the note (or confirm it still holds) with "
        "kb_update or by editing it",
        f"module/{module_id}",
    )


def _check_staleness(
    root: Path, config: Config, notes: list[_LoadedNote], findings: list[Finding]
) -> None:
    try:
        staleness = module_staleness(root, config)
    except UsageError:
        findings.append(
            Finding(
                "warning",
                "STALENESS_UNAVAILABLE",
                config.project.kb_dir,
                "this is not a git repository (or git failed), so staleness cannot be judged",
            )
        )
        return
    for module_id, state in staleness.items():
        if state.stale:
            findings.append(_stale_finding(config, module_id, state.reason))
    for loaded in notes:
        if not expand_sources(root, loaded.sources, config.structure.ignore):
            findings.append(
                Finding(
                    "warning",
                    "EMPTY_SOURCE_SET",
                    loaded.rel_path,
                    f"source set matches no files: {loaded.sources}",
                    str(loaded.note.meta.get("id")),
                )
            )


def _check_modules(root: Path, config: Config, findings: list[Finding]) -> None:
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
    obsolete = root / kb_dir / "INDEX.md"
    if obsolete.is_file():
        findings.append(
            Finding(
                "warning",
                "INDEX_OBSOLETE",
                f"{kb_dir}/INDEX.md",
                "this file is no longer used (the index is built from the notes on demand); "
                "delete it, and run `milepost overview` to print the index",
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


MAX_CITATIONS_CHECKED = 200
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def _check_citations(root: Path, notes: list[_LoadedNote], findings: list[Finding]) -> None:
    """Warn when a note cites a file or symbol that does not exist: a cheap, deterministic
    catch for invented details. It is deliberately lenient (a symbol counts if its name appears
    in the file), so it flags only what is clearly absent. It must never crash a check."""
    try:
        repo_paths = repo_files(root)
    except UsageError:
        return  # not a git repository: skip rather than guess
    by_name: dict[str, list[str]] = {}
    for path in repo_paths:
        by_name.setdefault(path.rsplit("/", 1)[-1], []).append(path)
    texts: dict[str, str] = {}
    for loaded in notes:
        note_id = str(loaded.note.meta.get("id"))
        for path, symbol in all_citations(loaded.note.body)[:MAX_CITATIONS_CHECKED]:
            try:
                problem = _citation_problem(root, repo_paths, by_name, texts, path, symbol)
            except (OSError, ValueError, RecursionError):
                continue  # unreadable or odd file: nothing to compare against
            if problem:
                findings.append(
                    Finding("warning", "CITATION_BROKEN", loaded.rel_path, problem, note_id)
                )


def _citation_problem(
    root: Path,
    repo_paths: list[str],
    by_name: dict[str, list[str]],
    texts: dict[str, str],
    path: str,
    symbol: str,
) -> str:
    if path.endswith("/"):
        prefix = path.lstrip("/")
        found = any(p.startswith(prefix) or ("/" + prefix) in "/" + p for p in repo_paths)
        return "" if found else f"cites the directory `{path}`, which is not in this repository"
    matches = [p for p in by_name.get(path.rsplit("/", 1)[-1], []) if path_matches(p, path)]
    if not matches:
        return f"cites `{path}`, which is not a file in this repository"
    wanted = symbol.split("(")[0].strip().rsplit(".", 1)[-1]
    if not symbol or len(matches) != 1 or not _IDENTIFIER.match(wanted):
        return ""
    if matches[0] not in texts:
        texts[matches[0]] = (root / matches[0]).read_text(encoding="utf-8", errors="replace")
    if re.search(rf"\b{re.escape(wanted)}\b", texts[matches[0]]):
        return ""
    return f"cites `{path}::{symbol}`, but `{wanted}` does not appear in {matches[0]}"


def _check_unreviewed_churn(root: Path, config: Config, findings: list[Finding]) -> None:
    try:
        statuses = module_statuses(root, config)
    except UsageError:
        return  # not a git repository, or git failed: churn is only a hint
    for status in statuses:
        if (
            status.never_reviewed
            or status.lines_changed_since <= config.visibility.churn_warn_lines
        ):
            continue
        note_path = f"{config.project.kb_dir}/modules/{status.module_id}.md"
        findings.append(
            Finding(
                "warning",
                "UNREVIEWED_CHURN",
                note_path,
                f"{status.lines_changed_since} lines of module/{status.module_id} changed since "
                f"its note was last reviewed ({status.commits_since} commit(s), "
                f"{status.agent_commits_since} look agent-authored); read it and run "
                f"`milepost review module/{status.module_id}`",
                f"module/{status.module_id}",
            )
        )


def _waived(finding: Finding, waivers: dict[str, str]) -> Finding:
    if finding.code in WAIVABLE and finding.severity == "failure" and finding.subject in waivers:
        reason = waivers[finding.subject]
        return replace(finding, severity="warning", message=f"{finding.message} (waived: {reason})")
    return finding


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
    new_dirs = {
        f"dir:{c.path}"
        for c in uncovered
        if not any(_matches_any(path, c.sources) for path in files_at(root, base, c.path))
    }

    def touches(patterns: list[str], paths: set[str]) -> bool:
        return any(_matches_any(p, patterns) and not _matches_any(p, ignore) for p in paths)

    note_paths = {n.note.meta.get("id"): n.rel_path for n in notes}
    kb_dir = config.project.kb_dir
    scoped: list[Finding] = []
    # STALE_NOTE in a pull request means: it changes covered code and does not touch the note.
    # That needs no stored hash and cannot conflict. Stale notes the range does not touch are old
    # debt and stay warnings.
    for module_id, module in config.modules.items():
        note_rel = f"{kb_dir}/modules/{module_id}.md"
        if f"module/{module_id}" not in note_paths:
            continue
        if touches(module.sources, changes.all) and note_rel not in changes.all:
            scoped.append(
                _stale_finding(config, module_id, "this change edits code the note describes")
            )
    in_range = {f.subject for f in scoped}
    for finding in findings:
        if finding.code == "STALE_NOTE":
            if finding.subject in in_range:
                continue
            finding = replace(finding, severity="warning")
        elif finding.code == "UNCOVERED_DIR":
            finding = replace(
                finding, severity="failure" if finding.subject in new_dirs else "warning"
            )
        scoped.append(finding)
    scoped = [_waived(finding, waivers) for finding in scoped]
    return scoped


def run_check(
    root: Path, config: Config, base: str | None = None, with_churn: bool = True
) -> CheckResult:
    findings: list[Finding] = []
    notes = _load_notes(root, config, findings)
    _check_staleness(root, config, notes, findings)
    _check_modules(root, config, findings)
    uncovered = _check_coverage(root, config, findings)
    _check_citations(root, notes, findings)
    if with_churn:
        _check_unreviewed_churn(root, config, findings)
    if base is not None:
        findings = _apply_ci_scope(root, base, config, findings, notes, uncovered)
    findings.sort(key=lambda f: (f.path, f.code, f.subject, f.message))
    return CheckResult(findings=findings, fail_on=config.check.fail_on)
