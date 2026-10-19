import subprocess
from pathlib import Path

import pytest
from support.embedders import HashEmbedder
from support.kb_repo import KbRepo
from typer.testing import CliRunner

from milepost import cli
from milepost.services.uninstall import run_uninstall

runner = CliRunner()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KbRepo:
    repo = KbRepo(tmp_path / "repo")
    repo.write("app/billing/api.py", "def charge(card):\n    return card\n")
    repo.write(".gitignore", "node_modules/\n.env\n")
    repo.commit("initial")
    monkeypatch.setattr(cli, "_embedder_for", lambda root: HashEmbedder())
    done = runner.invoke(
        cli.app, ["init", "--repo", str(repo.root), "--modules", "billing", "--yes"]
    )
    assert done.exit_code == 0, done.output
    repo.write_note_file("kb/modules/billing.md", "module/billing", ["app/billing/**/*.py"])
    repo.commit("milepost")
    return repo


def hooks_present(repo: KbRepo) -> list[str]:
    hooks = repo.root / ".git" / "hooks"
    return [n for n in ("pre-commit", "post-merge", "post-checkout") if (hooks / n).exists()]


def test_uninstall_when_not_confirmed_then_lists_actions_and_changes_nothing(repo: KbRepo) -> None:
    before = sorted(p.as_posix() for p in repo.root.rglob("*") if ".git/" not in p.as_posix())

    report = run_uninstall(repo.root, delete_notes=False, apply=False)

    after = sorted(p.as_posix() for p in repo.root.rglob("*") if ".git/" not in p.as_posix())
    assert before == after and hooks_present(repo)
    assert report.applied is False
    joined = " ".join(report.remove)
    assert "milepost.toml" in joined and "git hooks" in joined and "workflow" in joined


def test_uninstall_when_confirmed_then_removes_what_init_added_but_keeps_notes(
    repo: KbRepo,
) -> None:
    report = run_uninstall(repo.root, delete_notes=False, apply=True)

    assert report.applied is True
    assert not (repo.root / "milepost.toml").exists()
    assert not (repo.root / ".github/workflows/milepost.yml").exists()
    assert not (repo.root / ".gitattributes").exists()
    assert hooks_present(repo) == []
    assert not (repo.root / "kb/.index").exists()
    assert (repo.root / "kb/modules/billing.md").is_file()
    assert (repo.root / ".gitignore").read_text() == "node_modules/\n.env\n"
    config = subprocess.run(
        ["git", "config", "--get", "merge.milepost.driver"],
        cwd=repo.root,
        capture_output=True,
        text=True,
    )
    assert config.stdout.strip() == ""
    assert any("kb/" in line for line in report.keep)


def test_uninstall_when_delete_notes_and_notes_committed_then_notes_removed(repo: KbRepo) -> None:
    run_uninstall(repo.root, delete_notes=True, apply=True)

    assert not (repo.root / "kb").exists()
    assert repo.git("status", "--porcelain").count("kb/") >= 1  # shows as deletions to commit


def test_uninstall_when_delete_notes_and_notes_uncommitted_then_blocked_and_nothing_changes(
    repo: KbRepo,
) -> None:
    repo.write("kb/modules/billing.md", (repo.root / "kb/modules/billing.md").read_text() + "\nx\n")

    report = run_uninstall(repo.root, delete_notes=True, apply=True)

    assert report.applied is False and "uncommitted" in report.blocked
    assert (repo.root / "milepost.toml").exists() and hooks_present(repo)


def test_uninstall_when_workflow_was_edited_then_it_is_kept_and_reported(repo: KbRepo) -> None:
    workflow = repo.root / ".github/workflows/milepost.yml"
    workflow.write_text(workflow.read_text() + "# team change\n")

    report = run_uninstall(repo.root, delete_notes=False, apply=True)

    assert workflow.exists()
    assert any("workflow" in line and "edited" in line for line in report.keep)


def test_uninstall_when_foreign_hook_exists_then_it_is_not_touched(repo: KbRepo) -> None:
    hook = repo.root / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\necho mine\n")

    run_uninstall(repo.root, delete_notes=False, apply=True)

    assert hook.read_text() == "#!/bin/sh\necho mine\n"


def test_uninstall_when_gitattributes_has_other_lines_then_only_milepost_line_removed(
    repo: KbRepo,
) -> None:
    attributes = repo.root / ".gitattributes"
    attributes.write_text("*.png binary\n" + attributes.read_text())

    run_uninstall(repo.root, delete_notes=False, apply=True)

    assert attributes.read_text() == "*.png binary\n"


def test_uninstall_when_snippets_present_then_lists_manual_steps_and_leaves_files(
    repo: KbRepo,
) -> None:
    repo.write("CLAUDE.md", "# Project\n\n## Codebase knowledge base (milepost)\n\nUse kb.\n")
    repo.write(".github/CODEOWNERS", "kb/ @team\n*.py @other\n")

    report = run_uninstall(repo.root, delete_notes=False, apply=True)

    text = " ".join(report.manual)
    assert "CLAUDE.md" in text and "CODEOWNERS" in text and "--plugin-dir" in text
    assert "Codebase knowledge base" in (repo.root / "CLAUDE.md").read_text()


def test_uninstall_cli_when_run_without_yes_then_prints_plan_and_asks_for_yes(repo: KbRepo) -> None:
    result = runner.invoke(cli.app, ["uninstall", "--repo", str(repo.root)])

    assert result.exit_code == 0, result.output
    assert "would remove" in result.output and "--yes" in result.output
    assert (repo.root / "milepost.toml").exists()


def test_uninstall_cli_when_yes_then_removes_and_says_how_to_undo(repo: KbRepo) -> None:
    result = runner.invoke(cli.app, ["uninstall", "--repo", str(repo.root), "--yes"])

    assert result.exit_code == 0, result.output
    assert not (repo.root / "milepost.toml").exists()
    assert "git" in result.output and "restore" in result.output


def test_uninstall_cli_when_blocked_then_exit_two(repo: KbRepo) -> None:
    repo.write("kb/modules/new.md", "x\n")

    result = runner.invoke(
        cli.app, ["uninstall", "--repo", str(repo.root), "--delete-notes", "--yes"]
    )

    assert result.exit_code == 2 and "uncommitted" in result.output


def test_uninstall_when_nothing_installed_then_reports_nothing_to_do(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path / "bare")
    repo.commit("x")

    report = run_uninstall(repo.root, delete_notes=False, apply=True)

    assert report.remove == [] and report.applied is False


def test_uninstall_when_milepost_toml_is_invalid_then_it_is_still_removed(repo: KbRepo) -> None:
    repo.write("milepost.toml", "this is = not [valid toml\n")

    report = run_uninstall(repo.root, delete_notes=False, apply=True)

    assert report.applied is True and not (repo.root / "milepost.toml").exists()


def test_uninstall_when_delete_notes_and_only_index_is_untracked_then_not_blocked(
    repo: KbRepo,
) -> None:
    ignore = repo.root / ".gitignore"
    ignore.write_text(
        ignore.read_text().replace("kb/.index/\n", "").replace("kb/.progress.json\n", "")
    )
    repo.commit("drop kb ignore lines")
    repo.write("kb/.index/extra.bin", "x")

    report = run_uninstall(repo.root, delete_notes=True, apply=True)

    assert report.blocked == "" and report.applied is True
    assert not (repo.root / "kb/modules").exists()


def test_uninstall_when_gitignore_uses_crlf_then_other_lines_keep_their_endings(
    repo: KbRepo,
) -> None:
    (repo.root / ".gitignore").write_bytes(b"node_modules/\r\nkb/.index/\r\n.env")

    run_uninstall(repo.root, delete_notes=False, apply=True)

    assert (repo.root / ".gitignore").read_bytes() == b"node_modules/\r\n.env"


def test_uninstall_when_core_hooks_path_is_set_then_hook_manager_cleanup_is_listed(
    repo: KbRepo,
) -> None:
    repo.git("config", "core.hooksPath", ".githooks")  # milepost never writes hooks there

    report = run_uninstall(repo.root, delete_notes=False, apply=False)

    assert any("hook manager" in line for line in report.manual)


def test_uninstall_when_a_step_fails_then_earlier_steps_are_reported_and_exit_is_nonzero(
    repo: KbRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "unlink", broken)

    result = runner.invoke(cli.app, ["uninstall", "--repo", str(repo.root), "--yes"])

    assert result.exit_code != 0
    assert "stopped at" in result.output and "denied" in result.output


def test_uninstall_cli_when_blocked_and_no_yes_then_plan_is_still_printed_with_exit_zero(
    repo: KbRepo,
) -> None:
    repo.write("kb/modules/new.md", "x\n")

    result = runner.invoke(cli.app, ["uninstall", "--repo", str(repo.root), "--delete-notes"])

    assert result.exit_code == 0, result.output
    assert "blocked:" in result.output and "milepost.toml" in result.output


def test_uninstall_when_config_has_the_removed_model_setting_then_it_still_works(
    repo: KbRepo,
) -> None:
    repo.write(
        "milepost.toml", (repo.root / "milepost.toml").read_text() + '\n[draft]\nmode = "model"\n'
    )

    report = run_uninstall(repo.root, delete_notes=False, apply=True)

    assert report.applied is True and not (repo.root / "milepost.toml").exists()
