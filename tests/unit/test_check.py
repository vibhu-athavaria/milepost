from pathlib import Path

from support.kb_repo import KbRepo
from typer.testing import CliRunner

from milepost import cli
from milepost.config import load_config
from milepost.core.findings import Finding
from milepost.core.notes import read_note, write_note
from milepost.services.check import CheckResult, run_check

SERVICES = ["app/services/**/*.py"]


def make_repo(tmp_path: Path, extra_config: str = "") -> KbRepo:
    repo = KbRepo(tmp_path, extra_config)
    repo.add_module("services", SERVICES, {"app/services/a.py": "x = 1\n"})
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    return repo


def check(repo: KbRepo) -> CheckResult:
    return run_check(repo.root, load_config(repo.root / "milepost.toml"))


def codes(findings: list[Finding], severity: str | None = None) -> list[str]:
    return [f.code for f in findings if severity is None or f.severity == severity]


def test_check_when_note_is_current_then_no_findings(tmp_path: Path) -> None:
    assert check(make_repo(tmp_path)).findings == []


def test_check_when_source_changed_then_reports_stale_with_note_id(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/a.py", "x = 2\n")

    stale = [f for f in check(repo).findings if f.code == "STALE_NOTE"]

    assert len(stale) == 1
    assert stale[0].severity == "warning"  # stale notes only warn unless [check] stale = "fail"
    assert stale[0].subject == "module/services"
    assert stale[0].path == "kb/modules/services.md"


def test_check_when_module_has_no_note_then_reports_warning_not_failure(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module("services", SERVICES, {"app/services/a.py": "x\n"}, with_note=False)

    result = check(repo)

    assert codes(result.findings, "warning") == ["MISSING_NOTE"]
    assert codes(result.findings, "failure") == []
    assert result.exit_code == 0


def test_check_when_an_old_index_md_exists_then_warns_it_is_obsolete(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("kb/INDEX.md", "# Codebase index\n\nleft over from an older version\n")

    result = check(repo)

    assert "INDEX_OBSOLETE" in codes(result.findings, "warning")
    assert result.exit_code == 0


def test_check_when_no_index_md_then_no_index_finding(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    assert not [c for c in codes(check(repo).findings) if c.startswith("INDEX")]


def test_check_when_stale_and_stale_mode_is_warn_then_exit_zero(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/a.py", "x = 2\n")

    result = check(repo)

    assert "STALE_NOTE" in codes(result.findings, "warning")
    assert result.exit_code == 0


def test_check_when_stale_and_stale_mode_is_fail_then_exit_one(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, '\n[check]\nstale = "fail"\n')
    repo.write("app/services/a.py", "x = 2\n")

    result = check(repo)

    assert "STALE_NOTE" in codes(result.findings, "failure")
    assert result.exit_code == 1


def test_check_when_fail_on_none_and_stale_mode_fail_then_exit_zero(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, '\n[check]\nfail_on = "none"\nstale = "fail"\n')
    repo.write("app/services/a.py", "x = 2\n")

    result = check(repo)

    assert "STALE_NOTE" in codes(result.findings, "failure")
    assert result.exit_code == 0


def test_check_when_not_a_git_repository_then_says_staleness_cannot_be_judged(
    tmp_path: Path,
) -> None:
    (tmp_path / "milepost.toml").write_text(
        '[project]\nname = "x"\n\n[modules.a]\nsources = ["a/**/*.py"]\n'
    )
    (tmp_path / "a").mkdir()
    (tmp_path / "a/x.py").write_text("x = 1\n")

    result = run_check(tmp_path, load_config(tmp_path / "milepost.toml"))

    assert "STALENESS_UNAVAILABLE" in codes(result.findings, "warning")


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


def test_check_when_run_twice_then_findings_identical(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/a.py", "x = 2\n")
    repo.write("app/payments/p.py", "x\n")

    assert check(repo).findings == check(repo).findings


def test_check_when_reviewed_note_churn_over_threshold_then_warns_unreviewed_churn(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path, extra_config="\n[visibility]\nchurn_warn_lines = 1\n")
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    repo.write("app/services/a.py", "x = 1\ny = 2\nz = 3\n")
    repo.commit("big change")

    result = check(repo)

    assert "UNREVIEWED_CHURN" in codes(result.findings, "warning")


def test_check_when_note_never_reviewed_then_no_unreviewed_churn_warning(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path, "\n[visibility]\nchurn_warn_lines = 0\n")
    repo.add_module("services", SERVICES, {"app/services/a.py": "x = 1\n"}, status="draft")
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    repo.write("app/services/a.py", "x = 1\ny = 2\n")
    repo.commit("change")

    assert "UNREVIEWED_CHURN" not in codes(check(repo).findings)


def test_check_when_churn_over_threshold_then_still_exit_zero(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, extra_config="\n[visibility]\nchurn_warn_lines = 0\n")
    repo.write("app/services/a.py", "x = 1\ny = 2\n")
    repo.commit("change")
    repo.touch_note("services")
    repo.commit("note touched")

    assert check(repo).exit_code == 0


def citing_note(repo: KbRepo, body: str) -> None:
    note = read_note(repo.root / "kb/modules/services.md")
    note.body = body
    write_note(note, repo.root / "kb/modules/services.md")
    repo.commit("note with citations")


def test_check_when_note_cites_a_file_that_does_not_exist_then_warns_citation_broken(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    citing_note(repo, "\n## Purpose\n\nx.\n\n## Gotchas\n\n- See `app/services/ghost.py`.\n")

    findings = [f for f in check(repo).findings if f.code == "CITATION_BROKEN"]

    assert len(findings) == 1 and findings[0].severity == "warning"
    assert "ghost.py" in findings[0].message and findings[0].subject == "module/services"


def test_check_when_note_cites_a_symbol_that_does_not_exist_then_warns(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/a.py", "def real():\n    pass\n")
    repo.commit("symbols")
    note = read_note(repo.root / "kb/modules/services.md")
    note.meta["source_hash"] = repo.hash_of(SERVICES)
    write_note(note, repo.root / "kb/modules/services.md")
    citing_note(
        repo,
        "\n## Purpose\n\nx.\n\n## Entry points\n\n- `a.py::real` and `a.py::invented`.\n",
    )

    messages = [f.message for f in check(repo).findings if f.code == "CITATION_BROKEN"]

    assert len(messages) == 1 and "invented" in messages[0]


def test_check_when_citations_resolve_then_no_warning(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/a.py", "class Svc:\n    def run(self):\n        pass\n")
    repo.commit("symbols")
    note = read_note(repo.root / "kb/modules/services.md")
    note.meta["source_hash"] = repo.hash_of(SERVICES)
    write_note(note, repo.root / "kb/modules/services.md")
    citing_note(
        repo,
        "\n## Purpose\n\nx.\n\n## File map\n\n- `a.py`: services.\n\n"
        "## Invariants\n\n- Runs once: `a.py::Svc.run` and `Svc.run()` via `a.py::run`.\n",
    )

    assert "CITATION_BROKEN" not in codes(check(repo).findings)


def test_check_when_cited_file_lives_in_another_module_then_no_warning(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/core/deps.py", "x = 1\n")
    citing_note(repo, "\n## Purpose\n\nx.\n\n## Gotchas\n\n- Uses `app/core/deps.py`.\n")

    assert "CITATION_BROKEN" not in codes(check(repo).findings)


def test_check_when_no_churn_flag_then_cli_skips_the_churn_warning(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, extra_config="\n[visibility]\nchurn_warn_lines = 0\n")
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    repo.write("app/services/a.py", "x = 1\ny = 2\n")
    repo.commit("change")

    with_churn = CliRunner().invoke(cli.app, ["check", "--repo", str(repo.root)])
    without = CliRunner().invoke(cli.app, ["check", "--repo", str(repo.root), "--no-churn"])

    assert "UNREVIEWED_CHURN" in with_churn.output
    assert "UNREVIEWED_CHURN" not in without.output


def test_check_when_note_cites_a_directory_that_exists_then_no_warning(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    citing_note(repo, "\n## Purpose\n\nx.\n\n## File map\n\n- `app/services/`: the services.\n")

    assert "CITATION_BROKEN" not in codes(check(repo).findings)


def test_check_when_note_cites_a_directory_that_does_not_exist_then_warns(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    citing_note(repo, "\n## Purpose\n\nx.\n\n## File map\n\n- `app/ghosts/`: nothing here.\n")

    assert "CITATION_BROKEN" in codes(check(repo).findings, "warning")


def test_check_when_cited_symbol_is_a_class_attribute_then_no_warning(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/models.py", "class Settings:\n    timeout = 5\n")
    repo.commit("attribute")
    note = read_note(repo.root / "kb/modules/services.md")
    note.meta["source_hash"] = repo.hash_of(SERVICES)
    write_note(note, repo.root / "kb/modules/services.md")
    citing_note(
        repo, "\n## Purpose\n\nx.\n\n## Gotchas\n\n- `models.py::Settings.timeout` is read once.\n"
    )

    assert "CITATION_BROKEN" not in codes(check(repo).findings)


def test_check_when_cited_file_is_large_and_symbol_is_late_then_no_false_warning(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write(
        "app/services/big.py",
        "".join(f"def f{i}():\n    pass\n" for i in range(260)) + "def late_one():\n    pass\n",
    )
    repo.commit("big file")
    note = read_note(repo.root / "kb/modules/services.md")
    note.meta["source_hash"] = repo.hash_of(SERVICES)
    write_note(note, repo.root / "kb/modules/services.md")
    citing_note(repo, "\n## Purpose\n\nx.\n\n## Gotchas\n\n- See `big.py::late_one`.\n")

    assert "CITATION_BROKEN" not in codes(check(repo).findings)


def test_check_when_cited_file_cannot_be_read_then_check_does_not_crash(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/odd.py", "x = 1\n")
    repo.commit("odd")
    note = read_note(repo.root / "kb/modules/services.md")
    note.meta["source_hash"] = repo.hash_of(SERVICES)
    write_note(note, repo.root / "kb/modules/services.md")
    citing_note(repo, "\n## Purpose\n\nx.\n\n## Gotchas\n\n- See `odd.py::thing`.\n")
    (repo.root / "app/services/odd.py").unlink()  # listed by git, gone on disk

    check(repo)  # must not raise
