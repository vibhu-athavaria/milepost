import json
from pathlib import Path

from support.kb_repo import KbRepo
from typer.testing import CliRunner

from milepost.cli import app

runner = CliRunner()
SERVICES = ["app/services/**/*.py"]


def base_repo(tmp_path: Path) -> KbRepo:
    """A repo on `main` with one module, one reviewed note, and a clean check."""
    repo = KbRepo(tmp_path)
    repo.add_module("services", SERVICES, {"app/services/a.py": "x = 1\n"})
    repo.commit("base")
    return repo


def ci(repo: KbRepo, *extra: str) -> tuple[int, list[dict[str, str]], str]:
    result = runner.invoke(
        app,
        ["check", "--repo", str(repo.root), "--ci", "--base", "main", "--format", "json", *extra],
    )
    findings = json.loads(result.stdout) if result.exit_code != 2 else []
    return result.exit_code, findings, result.output


def find(findings: list[dict[str, str]], code: str) -> list[dict[str, str]]:
    return [f for f in findings if f["code"] == code]


def test_check_ci_when_changed_source_has_stale_note_then_fails(tmp_path: Path) -> None:
    repo = base_repo(tmp_path)
    repo.checkout("feature", create=True)
    repo.write("app/services/a.py", "x = 2\n")
    repo.commit("change source")

    code, findings, _ = ci(repo)

    assert code == 1
    assert find(findings, "STALE_NOTE")[0]["severity"] == "failure"


def test_check_ci_when_note_updated_in_same_pr_then_passes(tmp_path: Path) -> None:
    repo = base_repo(tmp_path)
    repo.checkout("feature", create=True)
    repo.write("app/services/a.py", "x = 2\n")
    repo.write_note_file("kb/modules/services.md", "module/services", "L2", SERVICES)
    repo.commit("change source and note")

    code, findings, _ = ci(repo)

    assert code == 0
    assert findings == []


def test_check_ci_when_waiver_trailer_present_then_downgrades_to_warning(tmp_path: Path) -> None:
    repo = base_repo(tmp_path)
    repo.checkout("feature", create=True)
    repo.write("app/services/a.py", "x = 2\n")
    repo.commit("change source\n\nKB-Waive: module/services prose is still accurate")

    code, findings, _ = ci(repo)

    assert code == 0
    stale = find(findings, "STALE_NOTE")[0]
    assert stale["severity"] == "warning"
    assert "prose is still accurate" in stale["message"]


def test_check_ci_when_waiver_without_reason_then_exit_two(tmp_path: Path) -> None:
    repo = base_repo(tmp_path)
    repo.checkout("feature", create=True)
    repo.write("app/services/a.py", "x = 2\n")
    repo.commit("change source\n\nKB-Waive: module/services")

    code, _, output = ci(repo)

    assert code == 2
    assert "KB-Waive" in output


def test_check_ci_when_stale_note_untouched_by_pr_then_warning_only(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module("services", SERVICES, {"app/services/a.py": "x = 1\n"})
    repo.write("app/services/a.py", "x = 2\n")  # stale before the PR starts
    repo.commit("base with existing debt")
    repo.checkout("feature", create=True)
    repo.write("README.md", "docs\n")
    repo.commit("unrelated change")

    code, findings, _ = ci(repo)

    assert code == 0
    assert find(findings, "STALE_NOTE")[0]["severity"] == "warning"


def test_check_ci_when_new_source_dir_uncovered_in_range_then_fails(tmp_path: Path) -> None:
    repo = base_repo(tmp_path)
    repo.checkout("feature", create=True)
    repo.write("app/payments/p.py", "x\n")
    repo.commit("add payments")

    code, findings, _ = ci(repo)

    assert code == 1
    uncovered = find(findings, "UNCOVERED_DIR")[0]
    assert uncovered["severity"] == "failure"
    assert "app/payments" in uncovered["message"]


def test_check_ci_when_uncovered_dir_predates_range_then_warning_only(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module("services", SERVICES, {"app/services/a.py": "x = 1\n"})
    repo.write("app/payments/p.py", "x\n")
    repo.commit("base with uncovered dir")
    repo.checkout("feature", create=True)
    repo.write("README.md", "docs\n")
    repo.commit("unrelated change")

    code, findings, _ = ci(repo)

    assert code == 0
    assert find(findings, "UNCOVERED_DIR")[0]["severity"] == "warning"


def test_check_ci_when_dir_waiver_trailer_present_then_downgrades_uncovered_dir(
    tmp_path: Path,
) -> None:
    repo = base_repo(tmp_path)
    repo.checkout("feature", create=True)
    repo.write("app/payments/p.py", "x\n")
    repo.commit("add payments\n\nKB-Waive: dir:app/payments scratch code, module comes later")

    code, findings, _ = ci(repo)

    assert code == 0
    assert find(findings, "UNCOVERED_DIR")[0]["severity"] == "warning"


def test_check_ci_when_l3_source_deleted_in_range_then_fails_orphan_note(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module(
        "services", SERVICES, {"app/services/a.py": "x = 1\n", "app/services/b.py": "y = 1\n"}
    )
    repo.add_file_note("app/services/b.py")
    repo.commit("base")
    repo.checkout("feature", create=True)
    (repo.root / "app/services/b.py").unlink()
    repo.commit("delete b")

    code, findings, _ = ci(repo)

    assert code == 1
    assert find(findings, "ORPHAN_NOTE")[0]["severity"] == "failure"


def test_check_ci_when_declared_module_has_no_note_then_still_warning_in_ci(
    tmp_path: Path,
) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module("services", SERVICES, {"app/services/a.py": "x\n"}, with_note=False)
    repo.commit("base")
    repo.checkout("feature", create=True)
    repo.write("README.md", "docs\n")
    repo.commit("unrelated")

    code, findings, _ = ci(repo)

    assert code == 0
    assert find(findings, "MISSING_NOTE")[0]["severity"] == "warning"
