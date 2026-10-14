"""`milepost report`: a review aid for a change range (SPEC section 8.4). Read-only."""

import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milepost.config import Config
from milepost.core.citations import citing_changed
from milepost.core.glob import expand_sources, matches_any
from milepost.core.notes import parse_note
from milepost.errors import NoteInvalid
from milepost.services.gitinfo import changed_files
from milepost.services.status import module_statuses
from milepost.structure.candidates import EXTENSIONS_BY_LANGUAGE


@dataclass
class NoteChange:
    path: str
    before: str
    after: str


@dataclass
class RiskyBullet:
    note_id: str
    section: str
    text: str
    path: str


@dataclass
class Report:
    base: str
    notes_changed: list[NoteChange] = field(default_factory=list)
    stale_notes: list[str] = field(default_factory=list)
    uncovered_files: list[str] = field(default_factory=list)
    risky: list[RiskyBullet] = field(default_factory=list)
    churn: list[str] = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        return any(
            [self.notes_changed, self.stale_notes, self.uncovered_files, self.risky, self.churn]
        )


def _status_at(root: Path, ref: str, rel: str) -> str:
    done = subprocess.run(
        ["git", "show", f"{ref}:{rel}"], cwd=root, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        return "(absent)"
    try:
        return str(parse_note(done.stdout).meta.get("status", "unknown"))
    except NoteInvalid:
        return "(invalid)"


def _merge_base(root: Path, base: str) -> str:
    done = subprocess.run(
        ["git", "merge-base", base, "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else base


def _under_a_root(path: str, config: Config) -> bool:
    return any(path.startswith(root.rstrip("/") + "/") for root in config.structure.roots)


def build_report(root: Path, config: Config, base: str) -> Report:
    changes = changed_files(root, base)
    fork_point = _merge_base(root, base)
    kb = config.project.kb_dir.rstrip("/") + "/"
    ignore = config.structure.ignore
    report = Report(base=base)

    for path in sorted(
        p for p in changes.all if p.startswith(f"{kb}modules/") and p.endswith(".md")
    ):
        after = "(deleted)" if path in changes.deleted else _status_at(root, "HEAD", path)
        report.notes_changed.append(NoteChange(path, _status_at(root, fork_point, path), after))

    source_changes = sorted(
        p
        for p in changes.all
        if not p.startswith(kb) and not matches_any(p, ignore) and p not in changes.deleted
    )
    extensions = tuple(
        ext for lang in config.structure.languages for ext in EXTENSIONS_BY_LANGUAGE.get(lang, [])
    )
    report.uncovered_files = [
        p
        for p in source_changes
        if p.endswith(extensions)
        and _under_a_root(p, config)
        and not any(matches_any(p, m.sources) for m in config.modules.values())
    ]

    changed = set(source_changes)
    for module_id, module in sorted(config.modules.items()):
        note_rel = f"{kb}modules/{module_id}.md"
        if (
            (root / note_rel).is_file()
            and note_rel not in changes.all
            and any(matches_any(p, module.sources) for p in source_changes)
        ):
            report.stale_notes.append(
                f"module/{module_id}: this change edits code the note covers and does not touch it"
            )
    for module_id, module in sorted(config.modules.items()):
        note_path = root / kb / "modules" / f"{module_id}.md"
        try:
            note = parse_note(note_path.read_text(encoding="utf-8"))
        except (OSError, NoteInvalid):
            continue
        candidates = set(expand_sources(root, module.sources, ignore))
        candidates |= {p for p in changed if matches_any(p, module.sources)}
        for bullet, path in citing_changed(note.body, candidates, changed):
            report.risky.append(
                RiskyBullet(f"module/{module_id}", bullet.section, bullet.text, path)
            )

    threshold = config.visibility.churn_warn_lines
    report.churn = [
        f"{s.module_id}: {s.lines_changed_since} lines changed since the last review"
        for s in module_statuses(root, config)
        if not s.never_reviewed and s.lines_changed_since > threshold
    ]
    return report


def render_markdown(report: Report) -> str:
    lines = ["## Milepost review aid", ""]
    if not report.needs_attention:
        return "\n".join([*lines, "Nothing needs attention.", ""])
    if report.notes_changed:
        lines += ["### Notes changed in this pull request", ""]
        lines += [f"- `{c.path}`: {c.before} -> {c.after}" for c in report.notes_changed]
        lines.append("")
    if report.stale_notes:
        lines += ["### Notes that are stale for the changed files", ""]
        lines += [f"- {text}" for text in report.stale_notes] + [""]
    if report.uncovered_files:
        lines += ["### Changed files no module covers", ""]
        lines += [f"- `{path}`" for path in report.uncovered_files] + [""]
    if report.risky:
        lines += ["### Changed code the notes call out", ""]
        lines += [
            f"- `{r.path}` is cited in {r.note_id} ({r.section}): {r.text}" for r in report.risky
        ]
        lines.append("")
    if report.churn:
        lines += ["### Unreviewed churn", ""]
        lines += [f"- {text}" for text in report.churn] + [""]
    return "\n".join(lines)


def report_as_dict(report: Report) -> dict[str, Any]:
    return {**asdict(report), "needs_attention": report.needs_attention}
