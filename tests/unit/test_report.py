import json
from pathlib import Path

from support.kb_repo import KbRepo
from typer.testing import CliRunner

from milepost import cli
from milepost.config import load_config
from milepost.core.notes import read_note, write_note
from milepost.services.report import Report, build_report, render_markdown, report_as_dict

runner = CliRunner()
SOURCES = ["app/billing/**/*.py"]
BODY = (
    "\n## Purpose\n\nBills customers.\n\n## Invariants\n\n"
    "- Charges never exceed the limit: `charge.py::charge`.\n"
)


def make_repo(tmp_path: Path, extra: str = "") -> KbRepo:
    repo = KbRepo(tmp_path / "repo", extra_config=extra)
    repo.add_module(
        "billing",
        SOURCES,
        {
            "app/billing/charge.py": "def charge(card):\n    return card\n",
            "app/other/x.py": "x = 1\n",
        },
        body=BODY,
    )
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    repo.checkout("feature", create=True)
    return repo


def report(repo: KbRepo) -> Report:
    return build_report(repo.root, load_config(repo.root / "milepost.toml"), "main")


def test_report_when_nothing_needs_attention_then_says_so(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("README.txt", "docs only\n")
    repo.commit("docs")

    built = report(repo)

    assert built.needs_attention is False
    assert "Nothing needs attention." in render_markdown(built)


def test_report_when_note_changed_then_lists_it_with_status_before_and_after(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    note = read_note(repo.root / "kb/modules/billing.md")
    note.meta["status"] = "draft"
    write_note(note, repo.root / "kb/modules/billing.md")
    repo.refresh_index()
    repo.commit("agent edits the note")

    (change,) = report(repo).notes_changed

    assert (change.path, change.before, change.after) == (
        "kb/modules/billing.md",
        "reviewed",
        "draft",
    )


def test_report_when_changed_file_has_stale_note_then_listed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")
    repo.commit("code only")

    built = report(repo)

    assert any("module/billing" in text for text in built.stale_notes)
    assert "Notes that are stale" in render_markdown(built)


def test_report_when_changed_file_uncovered_then_listed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/other/x.py", "x = 2\n")
    repo.commit("uncovered change")

    assert report(repo).uncovered_files == ["app/other/x.py"]


def test_report_when_invariant_cites_changed_file_then_bullet_quoted_with_note_id(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")
    repo.commit("code only")

    (risky,) = report(repo).risky

    assert risky.note_id == "module/billing" and risky.path == "app/billing/charge.py"
    assert "Charges never exceed the limit" in risky.text


def test_report_when_unreviewed_churn_over_threshold_then_listed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, extra="\n[visibility]\nchurn_warn_lines = 1\n")
    repo.write("app/billing/charge.py", "def charge(card):\n    return 1\n    # a\n    # b\n")
    repo.commit("big change")

    assert any(text.startswith("billing:") for text in report(repo).churn)


def test_report_when_format_json_then_parses(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/other/x.py", "x = 2\n")
    repo.commit("uncovered change")

    result = runner.invoke(
        cli.app, ["report", "--base", "main", "--format", "json", "--repo", str(repo.root)]
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["uncovered_files"] == ["app/other/x.py"]
    assert report_as_dict(report(repo))["needs_attention"] is True


def test_report_when_run_with_findings_then_exit_zero(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")
    repo.commit("stale")

    result = runner.invoke(cli.app, ["report", "--base", "main", "--repo", str(repo.root)])

    assert result.exit_code == 0 and "stale" in result.output


def test_status_cli_when_run_then_table_and_json(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    text = runner.invoke(cli.app, ["status", "--repo", str(repo.root)])
    data = runner.invoke(cli.app, ["status", "--repo", str(repo.root), "--json"])

    assert text.exit_code == 0 and "billing" in text.output
    assert json.loads(data.output)[0]["module_id"] == "billing"


def test_ci_workflow_when_written_then_report_step_writes_to_step_summary() -> None:
    text = (Path(cli.__file__).parent / "resources" / "ci-kb-check.yml").read_text()

    assert (
        'milepost report --base "origin/${{ github.base_ref }}" >> "$GITHUB_STEP_SUMMARY"' in text
    )


def test_codeowners_snippet_when_present_then_names_kb_directory() -> None:
    snippet = (Path(cli.__file__).parent.parent / "templates" / "CODEOWNERS.snippet").read_text()

    assert "/kb/" in snippet


def test_report_when_base_ref_missing_then_cli_prints_message_and_exits_zero(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    result = runner.invoke(
        cli.app, ["report", "--base", "origin/nonexistent", "--repo", str(repo.root)]
    )

    assert result.exit_code == 0 and "Report unavailable" in result.output


def test_report_when_changed_file_outside_source_roots_then_not_listed_as_uncovered(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("scripts/release.py", "x = 1\n")
    repo.commit("a script outside the roots")

    assert report(repo).uncovered_files == []


def test_report_when_uncovered_file_deleted_then_not_listed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo.root / "app/other/x.py").unlink()
    repo.commit("delete uncovered file")

    assert report(repo).uncovered_files == []


def test_report_when_main_moved_on_then_before_status_comes_from_the_fork_point(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.checkout("main")
    note = read_note(repo.root / "kb/modules/billing.md")
    note.meta["status"] = "draft"
    write_note(note, repo.root / "kb/modules/billing.md")
    repo.refresh_index()
    repo.commit("main flips the note to draft after the branch point")
    repo.checkout("feature")
    repo.write(
        "kb/modules/billing.md", (repo.root / "kb/modules/billing.md").read_text() + "\nNote.\n"
    )
    repo.commit("feature edits the note body")

    (change,) = report(repo).notes_changed

    assert change.before == "reviewed"
