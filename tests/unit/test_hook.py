import json
from pathlib import Path

import pytest
from support.kb_repo import KbRepo
from typer.testing import CliRunner

from milepost import cli
from milepost.services import hook

runner = CliRunner()
SOURCES = ["app/billing/**/*.py"]


def make_repo(tmp_path: Path, status: str = "reviewed") -> KbRepo:
    repo = KbRepo(tmp_path / "repo")
    repo.add_module(
        "billing",
        SOURCES,
        {"app/billing/charge.py": "def charge(card):\n    return card\n"},
        status=status,
    )
    repo.write("app/other/x.py", "x = 1\n")
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    return repo


def context_of(output: str) -> str:
    return str(json.loads(output)["hookSpecificOutput"]["additionalContext"])


def edit_payload(repo: KbRepo, path: str) -> dict[str, object]:
    return {"cwd": str(repo.root), "tool_input": {"file_path": str(repo.root / path)}}


def test_hook_session_start_when_kb_present_then_returns_index_cut_to_3000_chars_and_reminder(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    out = json.loads(hook.session_start(repo.root))

    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "| billing |" in text and "kb_module" in text and "stale note(s)" in text


def test_hook_session_start_when_index_is_huge_then_cut(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    index = repo.root / "kb/INDEX.md"
    index.write_text(index.read_text() + "| x | " + "long " * 2000 + " |\n")

    text = context_of(hook.session_start(repo.root))

    assert "index cut" in text and len(text) < 3600


def test_hook_session_start_when_no_kb_then_prints_nothing(tmp_path: Path) -> None:
    assert hook.session_start(tmp_path) == ""


def test_hook_post_edit_when_path_covered_then_returns_covering_notes_and_update_instruction(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    text = context_of(hook.post_edit(repo.root, edit_payload(repo, "app/billing/charge.py")))

    assert "module/billing (reviewed)" in text
    assert "kb_update" in text and "kb_sync" in text


def test_hook_post_edit_when_note_stale_then_marked_stale(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    text = context_of(hook.post_edit(repo.root, edit_payload(repo, "app/billing/charge.py")))

    assert "STALE" in text


def test_hook_post_edit_when_path_under_kb_dir_then_prints_nothing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    assert hook.post_edit(repo.root, edit_payload(repo, "kb/modules/billing.md")) == ""


def test_hook_post_edit_when_path_outside_repo_then_prints_nothing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    payload = {"cwd": str(repo.root), "tool_input": {"file_path": "/etc/hosts"}}

    assert hook.post_edit(repo.root, payload) == ""


def test_hook_post_edit_when_path_in_uncovered_dir_then_names_uncovered_dir(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    text = context_of(hook.post_edit(repo.root, edit_payload(repo, "app/other/x.py")))

    assert "UNCOVERED_DIR" in text and "app/other" in text


def test_hook_post_edit_when_no_file_path_then_prints_nothing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    assert hook.post_edit(repo.root, {"tool_input": {"command": "ls"}}) == ""


def test_hook_stop_when_check_fails_then_returns_block_with_findings(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    out = json.loads(hook.stop(repo.root, {"cwd": str(repo.root)}))

    assert out["decision"] == "block"
    assert "STALE_NOTE" in out["reason"] and "kb_update" in out["reason"]


def test_hook_stop_when_stop_hook_already_active_then_exits_zero_without_output(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    assert hook.stop(repo.root, {"stop_hook_active": True}) == ""


def test_hook_stop_when_check_passes_then_no_block(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    assert hook.stop(repo.root, {}) == ""


def test_hook_stop_when_stale_note_is_old_debt_unrelated_to_this_work_then_no_block(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")
    repo.commit("someone else made the note stale")
    repo.write("app/other/x.py", "x = 2\n")

    assert hook.stop(repo.root, {}) == ""


def test_hook_stop_when_not_a_milepost_repo_then_no_output(tmp_path: Path) -> None:
    assert hook.stop(tmp_path, {}) == ""


def test_hook_cli_when_milepost_errors_then_exits_zero_with_stderr_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(root: Path, payload: dict[str, object]) -> str:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "hook_post_edit_text", boom)

    result = runner.invoke(cli.app, ["hook", "post-edit"], input="{}")

    assert result.exit_code == 0
    assert "kaboom" in result.output


def test_hook_cli_when_given_edit_json_on_stdin_then_prints_context(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = runner.invoke(
        cli.app,
        ["hook", "post-edit"],
        input=json.dumps(edit_payload(repo, "app/billing/charge.py")),
    )

    assert result.exit_code == 0
    assert "module/billing" in context_of(result.output.strip())


def test_hook_cli_when_stdin_is_not_json_then_exits_zero_silently(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["hook", "stop"], input="not json")

    assert result.exit_code == 0 and result.output.strip() == ""
