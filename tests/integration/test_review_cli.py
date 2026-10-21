import pytest
from support.kb_repo import KbRepo
from typer.testing import CliRunner

from milepost import cli
from milepost.core.notes import read_note
from milepost.errors import EnvironmentProblem

runner = CliRunner()


@pytest.fixture
def repo(tmp_path_factory: pytest.TempPathFactory) -> KbRepo:
    repo = KbRepo(tmp_path_factory.mktemp("r") / "repo")
    repo.git("config", "user.name", "Jane Doe")
    repo.git("config", "user.email", "jane@example.com")
    repo.add_module(
        "billing",
        ["app/billing/**/*.py"],
        {"app/billing/api.py": "def charge(card):\n    return card\n"},
        status="draft",
    )
    return repo


def test_review_cli_when_run_then_note_reviewed_by_git_identity(repo: KbRepo) -> None:
    result = runner.invoke(cli.app, ["review", "module/billing", "--repo", str(repo.root)])

    assert result.exit_code == 0, result.output
    meta = read_note(repo.root / "kb/modules/billing.md").meta
    assert meta["status"] == "reviewed"
    assert meta["reviewed_by"] == "Jane Doe <jane@example.com>"


def test_review_cli_when_unknown_note_then_exit_two(repo: KbRepo) -> None:
    result = runner.invoke(cli.app, ["review", "module/nope", "--repo", str(repo.root)])

    assert result.exit_code == 2


def test_hooks_cli_when_install_then_uninstall_then_hooks_come_and_go(repo: KbRepo) -> None:
    installed = runner.invoke(cli.app, ["hooks", "install", "--repo", str(repo.root)])
    present = (repo.root / ".git/hooks/pre-commit").is_file()
    removed = runner.invoke(cli.app, ["hooks", "uninstall", "--repo", str(repo.root)])

    assert installed.exit_code == 0 and present
    assert removed.exit_code == 0
    assert not (repo.root / ".git/hooks/pre-commit").exists()


def two_drafts(repo: KbRepo) -> None:
    repo.add_module(
        "accounts",
        ["app/accounts/**/*.py"],
        {"app/accounts/models.py": "class Account:\n    pass\n"},
        status="draft",
    )


def status_of(repo: KbRepo, module_id: str) -> str:
    return str(read_note(repo.root / f"kb/modules/{module_id}.md").meta["status"])


def test_review_all_when_answers_are_yes_and_no_then_only_the_yes_note_is_reviewed(
    repo: KbRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    two_drafts(repo)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)

    result = runner.invoke(cli.app, ["review", "--all", "--repo", str(repo.root)], input="y\nn\n")

    assert result.exit_code == 0, result.output
    assert status_of(repo, "accounts") == "reviewed" and status_of(repo, "billing") == "draft"
    assert "1 of 2 marked reviewed" in result.output
    assert "=== module/accounts (1 of 2) ===" in result.output


def test_review_all_when_user_quits_then_remaining_notes_untouched(
    repo: KbRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    two_drafts(repo)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)

    result = runner.invoke(cli.app, ["review", "--all", "--repo", str(repo.root)], input="q\n")

    assert result.exit_code == 0, result.output
    assert status_of(repo, "accounts") == "draft" and status_of(repo, "billing") == "draft"
    assert "0 of 2 marked reviewed" in result.output


def test_review_all_when_not_interactive_then_exit_two_and_nothing_reviewed(repo: KbRepo) -> None:
    result = runner.invoke(cli.app, ["review", "--all", "--repo", str(repo.root)], input="y\n")

    assert result.exit_code == 2 and "interactive terminal" in result.output
    assert status_of(repo, "billing") == "draft"


def test_review_all_has_no_yes_option_because_approving_is_a_human_act(repo: KbRepo) -> None:
    result = runner.invoke(cli.app, ["review", "--all", "--yes", "--repo", str(repo.root)])

    assert result.exit_code == 2 and "No such option" in result.output


def test_review_all_when_answer_is_not_y_n_or_q_then_it_asks_again(
    repo: KbRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)

    result = runner.invoke(
        cli.app, ["review", "--all", "--repo", str(repo.root)], input="\nmaybe\ny\n"
    )

    assert result.exit_code == 0, result.output
    assert status_of(repo, "billing") == "reviewed"


def test_review_all_when_note_is_stale_then_it_is_skipped_without_showing_the_body(
    repo: KbRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    repo.commit("notes")
    repo.write("app/billing/api.py", "def charge(card):\n    return 'changed'\n")
    repo.commit("edit code, not the note")

    result = runner.invoke(cli.app, ["review", "--all", "--repo", str(repo.root)])

    assert "Stale" in result.output and "Skipped" in result.output
    assert "Describes the thing" not in result.output  # the body was not shown
    assert status_of(repo, "billing") == "draft"


def test_review_all_when_git_identity_missing_then_it_fails_once_before_any_prompt(
    repo: KbRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(
        cli, "git_identity", lambda root: (_ for _ in ()).throw(EnvironmentProblem("no identity"))
    )

    result = runner.invoke(cli.app, ["review", "--all", "--repo", str(repo.root)], input="y\n")

    assert result.exit_code == 3 and "no identity" in result.output
    assert status_of(repo, "billing") == "draft"


def test_review_all_when_input_ends_early_then_earlier_approvals_are_kept_and_reported(
    repo: KbRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    two_drafts(repo)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)

    result = runner.invoke(cli.app, ["review", "--all", "--repo", str(repo.root)], input="y\n")

    assert status_of(repo, "accounts") == "reviewed" and status_of(repo, "billing") == "draft"
    assert "Stopped." in result.output and "1 of 2 marked reviewed" in result.output


def test_review_when_neither_or_both_id_and_all_given_then_usage_error(repo: KbRepo) -> None:
    neither = runner.invoke(cli.app, ["review", "--repo", str(repo.root)])
    both = runner.invoke(cli.app, ["review", "module/billing", "--all", "--repo", str(repo.root)])

    assert neither.exit_code == 2 and both.exit_code == 2


def test_review_all_when_nothing_is_draft_then_says_so(
    repo: KbRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    runner.invoke(cli.app, ["review", "module/billing", "--repo", str(repo.root)])

    result = runner.invoke(cli.app, ["review", "--all", "--repo", str(repo.root)])

    assert result.exit_code == 0 and "nothing waiting for review" in result.output
