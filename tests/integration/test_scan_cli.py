import json
from pathlib import Path

from typer.testing import CliRunner

from kbmap.cli import app

runner = CliRunner()

CONFIG = """
[project]
name = "example"

[modules.services]
sources = ["app/services/**/*.py"]
"""


def make_repo(root: Path, config: str | None = CONFIG) -> Path:
    for rel in ["app/services/a.py", "app/ai/b.py"]:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    if config is not None:
        (root / "kbmap.toml").write_text(config)
    return root


def test_scan_command_when_run_after_init_then_lists_only_undeclared_candidates(
    tmp_path: Path,
) -> None:
    make_repo(tmp_path)

    result = runner.invoke(app, ["scan", "--json", "--repo", str(tmp_path)])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [candidate["id"] for candidate in data["candidates"]] == ["ai"]
    assert data["candidates"][0]["sources"] == ["app/ai/**/*.py"]


def test_scan_command_when_no_config_then_lists_all_candidates(tmp_path: Path) -> None:
    make_repo(tmp_path, config=None)

    result = runner.invoke(app, ["scan", "--json", "--repo", str(tmp_path)])

    assert result.exit_code == 0
    ids = sorted(candidate["id"] for candidate in json.loads(result.stdout)["candidates"])
    assert ids == ["ai", "services"]


def test_scan_command_when_run_then_config_file_unchanged(tmp_path: Path) -> None:
    make_repo(tmp_path)
    before = (tmp_path / "kbmap.toml").read_bytes()

    runner.invoke(app, ["scan", "--repo", str(tmp_path)])

    assert (tmp_path / "kbmap.toml").read_bytes() == before


def test_scan_command_when_text_output_then_prints_one_line_per_candidate(tmp_path: Path) -> None:
    make_repo(tmp_path)

    result = runner.invoke(app, ["scan", "--repo", str(tmp_path)])

    assert result.exit_code == 0
    assert "ai" in result.stdout
    assert "app/ai/**/*.py" in result.stdout


def test_scan_cli_when_config_invalid_then_exit_two_with_field_path(tmp_path: Path) -> None:
    make_repo(tmp_path, config=CONFIG.replace("modules.services", "modules.Services"))

    result = runner.invoke(app, ["scan", "--repo", str(tmp_path)])

    assert result.exit_code == 2
    assert "modules.Services" in result.output
