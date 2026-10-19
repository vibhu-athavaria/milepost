import json
from pathlib import Path

import pytest
from support.embedders import HashEmbedder
from support.kb_repo import KbRepo
from typer.testing import CliRunner

from milepost import cli

runner = CliRunner()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KbRepo:
    repo = KbRepo(tmp_path / "repo")
    repo.write("app/billing/api.py", "def charge(card):\n    return card\n")
    repo.commit("initial")
    monkeypatch.setattr(cli, "_embedder_for", lambda root: HashEmbedder())
    return repo


def test_init_when_yes_flag_then_no_prompt_declares_module_and_tells_claude_to_write_notes(
    repo: KbRepo,
) -> None:
    result = runner.invoke(
        cli.app, ["init", "--repo", str(repo.root), "--modules", "billing", "--yes"]
    )

    assert result.exit_code == 0, result.output
    assert "kb_draft_module" in result.output and "billing" in result.output
    assert "milepost review" in result.output
    assert not (repo.root / "kb/modules/billing.md").exists()


def test_init_when_not_confirmed_and_not_interactive_then_exit_two_and_nothing_written(
    repo: KbRepo,
) -> None:
    result = runner.invoke(cli.app, ["init", "--repo", str(repo.root), "--modules", "billing"])

    assert result.exit_code == 2
    assert "--yes" in result.output
    assert not (repo.root / "milepost.toml").exists()


def test_init_when_dry_run_then_lists_files_and_tokens_in_plain_words(repo: KbRepo) -> None:
    result = runner.invoke(
        cli.app, ["init", "--repo", str(repo.root), "--modules", "billing", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "app/billing/api.py" in result.output
    assert "Claude would read 1 file(s) to write the note" in result.output
    assert "estimated tokens" in result.output
    assert "mode" not in result.output.lower() and "would send" not in result.output
    assert not (repo.root / "milepost.toml").exists()


def test_init_cli_when_dry_run_and_file_looks_like_a_secret_then_warns_it_would_be_left_out(
    repo: KbRepo,
) -> None:
    repo.write("app/billing/keys.py", 'KEY = "AKIAABCDEFGHIJKLMNOP"\n')

    result = runner.invoke(
        cli.app, ["init", "--repo", str(repo.root), "--modules", "billing", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "app/billing/keys.py" in result.output and "secret_scan_allow" in result.output
    assert "AKIAABCDEFGHIJKLMNOP" not in result.output


def test_removed_options_and_commands_are_gone(repo: KbRepo) -> None:
    assert runner.invoke(cli.app, ["init", "--model-mode", "--repo", str(repo.root)]).exit_code == 2
    assert runner.invoke(cli.app, ["draft", "billing", "--repo", str(repo.root)]).exit_code == 2


def test_doctor_when_json_flag_then_output_parses(repo: KbRepo) -> None:
    result = runner.invoke(cli.app, ["doctor", "--repo", str(repo.root), "--json"])

    payload = json.loads(result.output)
    assert payload["ok"] is True
    names = {c["name"] for c in payload["checks"]}
    assert {"python", "git", "sqlite-fts5"} <= names
    assert not any("MODEL" in name or "litellm" in name for name in names)
    assert result.exit_code == 0
