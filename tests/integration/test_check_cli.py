import json
from pathlib import Path

from support.kb_repo import KbRepo
from typer.testing import CliRunner

from milepost.cli import app

runner = CliRunner()


def make_repo(tmp_path: Path) -> KbRepo:
    repo = KbRepo(tmp_path)
    repo.add_module("services", ["app/services/**/*.py"], {"app/services/a.py": "x = 1\n"})
    return repo


def test_check_cli_when_repo_clean_then_exit_zero(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = runner.invoke(app, ["check", "--repo", str(repo.root)])

    assert result.exit_code == 0


def test_check_cli_when_run_twice_then_output_identical(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/a.py", "x = 2\n")
    repo.write("app/payments/p.py", "x\n")

    first = runner.invoke(app, ["check", "--repo", str(repo.root)])
    second = runner.invoke(app, ["check", "--repo", str(repo.root)])

    assert first.exit_code == second.exit_code == 1
    assert first.output == second.output
    assert "STALE_NOTE" in first.output
    assert "kb/modules/services.md" in first.output


def test_check_cli_when_json_format_then_output_parses_and_matches_findings(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/services/a.py", "x = 2\n")

    result = runner.invoke(app, ["check", "--repo", str(repo.root), "--format", "json"])

    assert result.exit_code == 1
    findings = json.loads(result.stdout)
    assert [f["code"] for f in findings] == ["STALE_NOTE"]
    assert set(findings[0]) == {"severity", "code", "path", "message"}
    assert findings[0]["severity"] == "failure"
    assert findings[0]["path"] == "kb/modules/services.md"


def test_check_cli_when_config_invalid_then_exit_two(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    config = repo.root / "milepost.toml"
    config.write_text(config.read_text().replace("modules.services", "modules.Services"))

    result = runner.invoke(app, ["check", "--repo", str(repo.root)])

    assert result.exit_code == 2
    assert "modules.Services" in result.output


def test_check_cli_when_ci_without_base_then_exit_two(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = runner.invoke(app, ["check", "--repo", str(repo.root), "--ci"])

    assert result.exit_code == 2
    assert "--base" in result.output


def test_check_cli_when_format_unknown_then_exit_two(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = runner.invoke(app, ["check", "--repo", str(repo.root), "--format", "yaml"])

    assert result.exit_code == 2
