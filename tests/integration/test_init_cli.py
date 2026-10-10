import json
from pathlib import Path

import pytest
from support.embedders import HashEmbedder
from support.kb_repo import KbRepo
from typer.testing import CliRunner

from milepost import cli
from milepost.core.notes import read_note
from milepost.services.doctor import run_doctor

runner = CliRunner()
BODY = "## Purpose\n\nDoes the thing.\n"


def no_keys(model: str) -> list[str]:
    return []


class FakeClient:
    def complete(self, model: str, system: str, user: str) -> str:
        return BODY


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KbRepo:
    repo = KbRepo(tmp_path / "repo")
    repo.write("app/billing/api.py", "def charge(card):\n    return card\n")
    repo.commit("initial")
    monkeypatch.setattr(cli, "_llm_client", lambda: FakeClient())
    monkeypatch.setattr(cli, "_embedder_for", lambda root: HashEmbedder())
    monkeypatch.delenv("MILEPOST_MODEL", raising=False)
    return repo


def test_init_when_yes_flag_then_no_prompt_and_runs_to_completion(
    repo: KbRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MILEPOST_MODEL", "fake/model")

    result = runner.invoke(
        cli.app, ["init", "--repo", str(repo.root), "--modules", "billing", "--yes"]
    )

    assert result.exit_code == 0, result.output
    assert read_note(repo.root / "kb/modules/billing.md").meta["status"] == "draft"
    assert "milepost review" in result.output


def test_init_when_not_confirmed_and_not_interactive_then_exit_two_and_nothing_written(
    repo: KbRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MILEPOST_MODEL", "fake/model")

    result = runner.invoke(cli.app, ["init", "--repo", str(repo.root), "--modules", "billing"])

    assert result.exit_code == 2
    assert "--yes" in result.output
    assert not (repo.root / "milepost.toml").exists()


def test_init_when_model_comes_from_dotenv_then_drafting_works(repo: KbRepo) -> None:
    repo.write(".env", "MILEPOST_MODEL=fake/model\n")

    result = runner.invoke(
        cli.app, ["init", "--repo", str(repo.root), "--modules", "billing", "--yes"]
    )

    assert result.exit_code == 0, result.output
    assert (repo.root / "kb/modules/billing.md").is_file()


def test_init_when_model_unset_then_exit_three_naming_variable(repo: KbRepo) -> None:
    result = runner.invoke(
        cli.app, ["init", "--repo", str(repo.root), "--modules", "billing", "--yes"]
    )

    assert result.exit_code == 3
    assert "MILEPOST_MODEL" in result.output


def test_init_when_dry_run_then_lists_files_and_tokens(repo: KbRepo) -> None:
    result = runner.invoke(
        cli.app, ["init", "--repo", str(repo.root), "--modules", "billing", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "app/billing/api.py" in result.output
    assert "estimated tokens" in result.output
    assert not (repo.root / "milepost.toml").exists()


def test_doctor_when_json_flag_then_output_parses(
    repo: KbRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "run_doctor", lambda root, environ: run_doctor(root, {}, no_keys))

    result = runner.invoke(cli.app, ["doctor", "--repo", str(repo.root), "--json"])

    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert any(c["name"] == "MILEPOST_MODEL" and c["status"] == "fail" for c in payload["checks"])
    assert result.exit_code == 3


def test_draft_when_run_then_note_written_as_draft(
    repo: KbRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MILEPOST_MODEL", "fake/model")
    runner.invoke(cli.app, ["init", "--repo", str(repo.root), "--modules", "billing", "--yes"])
    (repo.root / "kb/modules/billing.md").unlink()

    result = runner.invoke(cli.app, ["draft", "billing", "--repo", str(repo.root)])

    assert result.exit_code == 0, result.output
    assert read_note(repo.root / "kb/modules/billing.md").meta["status"] == "draft"
