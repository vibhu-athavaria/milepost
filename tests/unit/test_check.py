from pathlib import Path

from support.kb_repo import KbRepo

from milepost.config import load_config
from milepost.core.findings import Finding
from milepost.core.notes import read_note, write_note
from milepost.services.check import CheckResult, run_check

SERVICES = ["app/services/**/*.py"]


def make_repo(tmp_path: Path, extra_config: str = "") -> KbRepo:
    repo = KbRepo(tmp_path, extra_config)
    repo.add_module("services", SERVICES, {"app/services/a.py": "x = 1\n"})
    return repo


def check(repo: KbRepo) -> CheckResult:
    return run_check(repo.root, load_config(repo.root / "milepost.toml"))


def codes(findings: list[Finding], severity: str | None = None) -> list[str]:
    return [f.code for f in findings if severity is None or f.severity == severity]


def test_check_when_note_hash_matches_then_no_findings(tmp_path: Path) -> None:
    assert check(make_repo(tmp_path)).findings == []


def test_check_when_source_changed_then_reports_stale_with_note_id(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/a.py", "x = 2\n")

    stale = [f for f in check(repo).findings if f.code == "STALE_NOTE"]

    assert len(stale) == 1
    assert stale[0].severity == "failure"
    assert stale[0].subject == "module/services"
    assert stale[0].path == "kb/modules/services.md"


def test_check_when_module_has_no_note_then_reports_warning_not_failure(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module("services", SERVICES, {"app/services/a.py": "x\n"}, with_note=False)

    result = check(repo)

    assert codes(result.findings, "warning") == ["MISSING_NOTE"]
    assert codes(result.findings, "failure") == []
    assert result.exit_code == 0


def test_check_when_index_md_drifted_then_reports_failure(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("kb/INDEX.md", "# Codebase index\n\nhand edited\n")

    assert "INDEX_DRIFT" in codes(check(repo).findings, "failure")


def test_check_when_index_md_missing_then_reports_failure(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo.root / "kb" / "INDEX.md").unlink()

    assert "INDEX_DRIFT" in codes(check(repo).findings, "failure")


def test_check_when_source_hash_conflict_then_reports_failure_with_rehash_hint(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.set_hash("kb/modules/services.md", "CONFLICT")

    findings = check(repo).findings

    conflict = [f for f in findings if f.code == "SOURCE_HASH_CONFLICT"]
    assert len(conflict) == 1
    assert "milepost rehash module/services" in conflict[0].message
    assert "STALE_NOTE" not in codes(findings)


def test_check_when_fail_on_none_then_exit_zero_despite_stale(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, '\n[check]\nfail_on = "none"\n')
    repo.write("app/services/a.py", "x = 2\n")

    result = check(repo)

    assert "STALE_NOTE" in codes(result.findings, "failure")
    assert result.exit_code == 0


def test_check_when_stale_and_fail_on_stale_then_exit_one(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/a.py", "x = 2\n")

    assert check(repo).exit_code == 1


def test_check_when_note_has_no_frontmatter_then_reports_note_invalid(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("kb/modules/broken.md", "just text\n")

    findings = check(repo).findings

    assert [f.path for f in findings if f.code == "NOTE_INVALID"] == ["kb/modules/broken.md"]


def test_check_when_note_frontmatter_invalid_then_reports_validation_findings(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    note = repo.root / "kb" / "modules" / "services.md"
    note.write_text(note.read_text().replace("status: reviewed", "status: final"))

    assert "INVALID_STATUS" in codes(check(repo).findings, "failure")


def test_check_when_source_set_matches_no_files_then_warns(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    for path in (repo.root / "app" / "services").glob("*.py"):
        path.unlink()

    assert "EMPTY_SOURCE_SET" in codes(check(repo).findings, "warning")


def test_check_when_dir_under_root_matches_no_module_then_warns_uncovered_dir(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/payments/p.py", "x\n")

    uncovered = [f for f in check(repo).findings if f.code == "UNCOVERED_DIR"]

    assert [f.subject for f in uncovered] == ["dir:app/payments"]
    assert uncovered[0].severity == "warning"


def test_check_when_dir_covered_by_module_then_no_uncovered_warning(tmp_path: Path) -> None:
    assert "UNCOVERED_DIR" not in codes(check(make_repo(tmp_path)).findings)


def test_check_when_l3_sources_match_no_files_then_warns_orphan_note(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/b.py", "y\n")
    repo.add_file_note("app/services/b.py")
    (repo.root / "app/services/b.py").unlink()

    orphan = [f for f in check(repo).findings if f.code == "ORPHAN_NOTE"]

    assert [f.subject for f in orphan] == ["file/app/services/b.py"]
    assert orphan[0].severity == "warning"


def test_check_when_l3_and_l4_count_over_max_then_warns_detail_note_count(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "\n[check]\nmax_detail_notes = 1\n")
    for name in ["b.py", "c.py"]:
        repo.write(f"app/services/{name}", "y\n")
        repo.add_file_note(f"app/services/{name}")
    repo.write_note_file("kb/passages/x.md", "passage/x", "L4", [])
    # Hashes of the L2 note changed when files were added; refresh it so only the count remains.
    repo.write_note_file("kb/modules/services.md", "module/services", "L2", SERVICES)

    findings = check(repo).findings

    assert [f.code for f in findings if f.code == "DETAIL_NOTE_COUNT"] == ["DETAIL_NOTE_COUNT"]


def test_check_when_l3_and_l4_count_at_max_then_no_warning(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "\n[check]\nmax_detail_notes = 1\n")
    repo.write("app/services/b.py", "y\n")
    repo.add_file_note("app/services/b.py")
    repo.write_note_file("kb/modules/services.md", "module/services", "L2", SERVICES)

    assert "DETAIL_NOTE_COUNT" not in codes(check(repo).findings)


def test_check_when_run_twice_then_findings_identical(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/a.py", "x = 2\n")
    repo.write("app/payments/p.py", "x\n")

    assert check(repo).findings == check(repo).findings


def test_check_when_purpose_edited_and_index_not_rewritten_then_index_drift(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    note = read_note(repo.root / "kb/modules/services.md")
    note.body = note.body.replace("Describes the thing.", "Now describes another thing.")
    write_note(note, repo.root / "kb/modules/services.md")

    assert "INDEX_DRIFT" in codes(check(repo).findings, "failure")

    repo.refresh_index()

    assert check(repo).findings == []
