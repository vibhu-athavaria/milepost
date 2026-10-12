from importlib.metadata import version

from typer.testing import CliRunner

from milepost.cli import app

runner = CliRunner()

# Every command and command group in SPEC section 8.
EXPECTED_COMMANDS = [
    "init",
    "check",
    "index",
    "draft",
    "review",
    "rehash",
    "search",
    "hooks",
    "merge-driver",
    "serve",
    "doctor",
    "scan",
    "hook",
    "outline",
    "impact",
    "sync",
]


def test_cli_help_when_invoked_then_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in EXPECTED_COMMANDS:
        assert command in result.output, f"{command} missing from --help"


def test_cli_version_when_invoked_then_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert version("milepost") in result.output
