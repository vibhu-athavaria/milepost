import subprocess
from pathlib import Path

import pytest

from milepost.env import dotenv_is_ignored, load_env


def test_load_env_when_dotenv_present_then_values_available(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("MILEPOST_MODEL=openrouter/x/y\nOPENROUTER_API_KEY='sk-or-1'\n")
    environ: dict[str, str] = {}

    load_env(tmp_path, environ)

    assert environ == {"MILEPOST_MODEL": "openrouter/x/y", "OPENROUTER_API_KEY": "sk-or-1"}


def test_load_env_when_shell_value_set_then_shell_wins(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("MILEPOST_MODEL=from-file\nOTHER=file\n")
    environ = {"MILEPOST_MODEL": "from-shell"}

    load_env(tmp_path, environ)

    assert environ == {"MILEPOST_MODEL": "from-shell", "OTHER": "file"}


def test_load_env_when_no_dotenv_then_nothing_changes(tmp_path: Path) -> None:
    environ = {"A": "1"}

    load_env(tmp_path, environ)

    assert environ == {"A": "1"}


def test_load_env_when_value_empty_then_not_treated_as_set(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("MILEPOST_MODEL=\n")
    environ: dict[str, str] = {}

    load_env(tmp_path, environ)

    assert "MILEPOST_MODEL" not in environ


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def test_dotenv_is_ignored_when_listed_in_gitignore_then_true(git_repo: Path) -> None:
    (git_repo / ".env").write_text("A=1\n")
    (git_repo / ".gitignore").write_text(".env\n")

    assert dotenv_is_ignored(git_repo) is True


def test_dotenv_is_ignored_when_not_listed_then_false(git_repo: Path) -> None:
    (git_repo / ".env").write_text("A=1\n")

    assert dotenv_is_ignored(git_repo) is False


def test_dotenv_is_ignored_when_no_dotenv_then_true(git_repo: Path) -> None:
    assert dotenv_is_ignored(git_repo) is True


def test_load_env_when_dotenv_sets_milepost_disabled_then_it_is_ignored(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("MILEPOST_DISABLED=1\nOTHER=x\n")
    environ: dict[str, str] = {}

    load_env(tmp_path, environ)

    assert environ == {"OTHER": "x"}
