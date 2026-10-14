import json
from pathlib import Path

import pytest
from support.kb_repo import KbRepo
from typer.testing import CliRunner

from milepost import cli

runner = CliRunner()


@pytest.fixture
def repo(tmp_path_factory: pytest.TempPathFactory) -> KbRepo:
    repo = KbRepo(tmp_path_factory.mktemp("r") / "repo")
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.add_module(
        "billing",
        ["app/billing/**/*.py"],
        {
            "app/billing/charge.py": "def charge(card):\n    return card\n",
            "app/api/routes.py": "from app.billing.charge import charge\n",
        },
    )
    repo.commit("base")
    return repo


def invoke(repo: KbRepo, *args: str) -> str:
    result = runner.invoke(cli.app, [*args, "--repo", str(repo.root)])
    assert result.exit_code == 0, result.output
    return result.output


def test_cli_outline_impact_sync_when_json_flag_then_output_parses(repo: KbRepo) -> None:
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    outline = json.loads(invoke(repo, "outline", "app/billing/charge.py", "--json"))
    impact = json.loads(invoke(repo, "impact", "app/billing/charge.py", "--json"))
    sync = json.loads(invoke(repo, "sync", "--json"))

    assert outline["symbols"][0]["name"] == "charge"
    assert impact["importers"] == ["app/api/routes.py"]
    assert sync["changes"][0]["path"] == "app/billing/charge.py"


def test_cli_outline_when_text_then_line_ranges_printed(repo: KbRepo) -> None:
    output = invoke(repo, "outline", "app/billing/charge.py")

    assert "1-2  function  def charge(card):" in output


def test_cli_impact_when_text_then_importers_and_caveat_printed(repo: KbRepo) -> None:
    output = invoke(repo, "impact", "app/billing/charge.py")

    assert "app/api/routes.py" in output
    assert "static import graph" in output


def test_cli_sync_when_text_then_next_steps_printed(repo: KbRepo) -> None:
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    output = invoke(repo, "sync")

    assert "modified" in output and "Next:" in output and "kb_check" in output


def test_cli_outline_when_unsupported_file_then_exit_two(repo: KbRepo) -> None:
    repo.write("notes.rb", "a\n")

    result = runner.invoke(cli.app, ["outline", "notes.rb", "--repo", str(repo.root)])

    assert result.exit_code == 2


def test_cli_impact_when_file_missing_then_exit_two(repo: KbRepo) -> None:
    result = runner.invoke(cli.app, ["impact", "nope.py", "--repo", str(repo.root)])

    assert result.exit_code == 2


def test_cli_impact_and_sync_when_no_milepost_toml_then_work(tmp_path: Path) -> None:
    bare = KbRepo(tmp_path / "bare")
    bare.write("app/charge.py", "def charge(card):\n    return card\n")
    bare.write("app/routes.py", "from app.charge import charge\n")
    bare.git("config", "user.name", "t")
    bare.git("config", "user.email", "t@example.com")
    bare.commit("base")
    bare.write("app/charge.py", "def charge(card):\n    return 1\n")

    impact = runner.invoke(cli.app, ["impact", "app/charge.py", "--repo", str(bare.root)])
    sync = runner.invoke(cli.app, ["sync", "--repo", str(bare.root)])

    assert impact.exit_code == 0 and "app/routes.py" in impact.output
    assert sync.exit_code == 0 and "app/charge.py" in sync.output
