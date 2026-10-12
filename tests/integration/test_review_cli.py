import pytest
from support.kb_repo import KbRepo
from typer.testing import CliRunner

from milepost import cli
from milepost.core.notes import read_note

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


def test_rehash_when_non_interactive_and_no_yes_then_exit_two(repo: KbRepo) -> None:
    repo.set_hash("kb/modules/billing.md", "CONFLICT")

    result = runner.invoke(cli.app, ["rehash", "module/billing", "--repo", str(repo.root)])

    assert result.exit_code == 2
    assert "--yes" in result.output
    assert read_note(repo.root / "kb/modules/billing.md").meta["source_hash"] == "CONFLICT"


def test_rehash_when_conflict_then_sets_hash_and_prints_manifest_diff(repo: KbRepo) -> None:
    repo.set_hash("kb/modules/billing.md", "CONFLICT")

    result = runner.invoke(cli.app, ["rehash", "module/billing", "--repo", str(repo.root), "--yes"])

    assert result.exit_code == 0, result.output
    assert "old hash: CONFLICT" in result.output
    assert "app/billing/api.py" in result.output
    assert read_note(repo.root / "kb/modules/billing.md").meta["source_hash"] == repo.hash_of(
        ["app/billing/**/*.py"]
    )


def test_hooks_cli_when_install_then_uninstall_then_hooks_come_and_go(repo: KbRepo) -> None:
    installed = runner.invoke(cli.app, ["hooks", "install", "--repo", str(repo.root)])
    present = (repo.root / ".git/hooks/pre-commit").is_file()
    removed = runner.invoke(cli.app, ["hooks", "uninstall", "--repo", str(repo.root)])

    assert installed.exit_code == 0 and present
    assert removed.exit_code == 0
    assert not (repo.root / ".git/hooks/pre-commit").exists()
