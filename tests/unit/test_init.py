import importlib.util
import socket
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from support.embedders import HashEmbedder
from support.kb_repo import KbRepo

from milepost.config import load_config
from milepost.core.notes import read_note
from milepost.errors import EnvironmentProblem, UsageError
from milepost.services.init import InitReport, run_init

BODY = "## Purpose\n\nDoes the thing.\n"
ENV = {"MILEPOST_MODEL": "fake/model"}


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, model: str, system: str, user: str) -> str:
        self.calls += 1
        return BODY


def no_sleep(seconds: float) -> None:
    pass


def make_repo(tmp_path: Path) -> KbRepo:
    repo = KbRepo(tmp_path / "repo")
    repo.write("app/billing/api.py", "def charge(card):\n    return card\n")
    repo.write("app/accounts/models.py", "class Account:\n    pass\n")
    repo.commit("initial")
    return repo


def init(
    repo: KbRepo,
    client: FakeClient | None = None,
    modules: list[str] | None = None,
    dry_run: bool = False,
    force_config: bool = False,
    environ: dict[str, str] | None = None,
    model_mode: bool = True,
) -> InitReport:
    return run_init(
        repo.root,
        modules=modules,
        dry_run=dry_run,
        force_config=force_config,
        client=client or FakeClient(),
        embedder=HashEmbedder(),
        environ=ENV if environ is None else environ,
        now="2026-10-10T09:00:00Z",
        sleep=no_sleep,
        model_mode=model_mode,
    )


def test_init_when_not_git_repo_then_exit_three(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()

    with pytest.raises(EnvironmentProblem) as error:
        init_in(tmp_path)

    assert error.value.exit_code == 3


def init_in(path: Path) -> InitReport:
    return run_init(
        path,
        modules=None,
        dry_run=False,
        force_config=False,
        client=FakeClient(),
        embedder=HashEmbedder(),
        environ=ENV,
        now="2026-10-10T09:00:00Z",
        sleep=no_sleep,
    )


def test_init_when_scan_runs_then_no_module_activated_automatically(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    client = FakeClient()

    report = init(repo, client)

    config = tomllib.loads((repo.root / "milepost.toml").read_text())
    assert config.get("modules", {}) == {}
    assert "# [modules.billing]" in (repo.root / "milepost.toml").read_text()
    assert client.calls == 0
    assert report.drafted == []
    assert (repo.root / "kb").is_dir()


def test_init_when_modules_flag_then_declares_only_named_candidates(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    report = init(repo, modules=["billing"])

    config = load_config(repo.root / "milepost.toml")
    assert list(config.modules) == ["billing"]
    assert config.modules["billing"].sources == ["app/billing/**/*.py"]
    assert report.drafted == ["billing"]
    note = read_note(repo.root / "kb/modules/billing.md")
    assert note.meta["status"] == "draft"
    assert not (repo.root / "kb/modules/accounts.md").exists()
    assert not (repo.root / "kb/INDEX.md").exists()
    assert (repo.root / "kb/.index/index.sqlite").is_file()


def test_init_when_modules_flag_names_non_candidate_then_exit_two(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(UsageError) as error:
        init(repo, modules=["nonsense"])

    assert error.value.exit_code == 2
    assert not (repo.root / "milepost.toml").exists()


def test_init_when_run_twice_then_second_run_creates_nothing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    client = FakeClient()
    init(repo, client, modules=["billing"])
    calls_after_first = client.calls

    second = init(repo, client, modules=["billing"])

    assert second.created == []
    assert second.drafted == []
    assert client.calls == calls_after_first


def test_init_when_kb_note_exists_then_not_overwritten(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    init(repo, modules=["billing"])
    note_path = repo.root / "kb/modules/billing.md"
    note_path.write_text(note_path.read_text() + "\nHand-written addition.\n")
    before = note_path.read_bytes()
    client = FakeClient()

    init(repo, client, modules=["billing"])

    assert note_path.read_bytes() == before
    assert client.calls == 0


def test_init_when_config_exists_and_modules_flag_then_appends_only_new_module_tables(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    init(repo, modules=["billing"])

    init(repo, modules=["accounts"])

    config = load_config(repo.root / "milepost.toml")
    assert sorted(config.modules) == ["accounts", "billing"]
    assert (repo.root / "kb/modules/accounts.md").is_file()


def test_init_when_config_exists_and_modules_flag_then_rest_of_file_byte_identical(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    init(repo, modules=["billing"])
    before = (repo.root / "milepost.toml").read_bytes()

    init(repo, modules=["accounts"])

    after = (repo.root / "milepost.toml").read_bytes()
    assert after.startswith(before)
    assert after[len(before) :].count(b"[modules.") == 1


def test_init_when_dry_run_then_no_files_written_and_no_network_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)

    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network used during --dry-run")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    before = sorted(
        p.relative_to(repo.root).as_posix()
        for p in repo.root.rglob("*")
        if ".git/" not in p.as_posix()
    )
    client = FakeClient()

    report = init(repo, client, modules=["billing", "accounts"], dry_run=True)

    after = sorted(
        p.relative_to(repo.root).as_posix()
        for p in repo.root.rglob("*")
        if ".git/" not in p.as_posix()
    )
    assert after == before
    assert client.calls == 0
    assert report.dry_run is True
    assert report.planned_files == {
        "billing": ["app/billing/api.py"],
        "accounts": ["app/accounts/models.py"],
    }
    assert report.estimated_tokens > 0


def test_init_when_drafting_needed_and_model_unset_then_fails_before_writing(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(EnvironmentProblem, match="MILEPOST_MODEL"):
        init(repo, modules=["billing"], environ={})

    assert not (repo.root / "milepost.toml").exists()


def test_init_when_ci_workflow_absent_then_written_with_installed_version_pinned(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    init(repo)

    workflow = (repo.root / ".github/workflows/milepost.yml").read_text()
    assert f"milepost=={version('milepost')}" in workflow
    assert workflow.count("milepost==") == 2


def test_init_when_ci_workflow_exists_then_not_overwritten(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write(".github/workflows/milepost.yml", "name: mine\n")

    init(repo)

    assert (repo.root / ".github/workflows/milepost.yml").read_text() == "name: mine\n"


def test_init_when_run_then_gitignore_lists_dotenv(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write(".gitignore", "node_modules/\n")

    init(repo)

    lines = (repo.root / ".gitignore").read_text().splitlines()
    assert lines[0] == "node_modules/"
    assert {".env", "kb/.index/", "kb/.progress.json"} <= set(lines)


def test_init_when_run_then_gitattributes_has_merge_driver_line_once(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    init(repo)
    init(repo)

    text = (repo.root / ".gitattributes").read_text()
    assert text.count("kb/**/*.md merge=milepost") == 1


def test_init_when_force_config_then_config_rewritten_from_scratch(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    init(repo, modules=["billing"])

    init(repo, modules=["accounts"], force_config=True)

    assert list(load_config(repo.root / "milepost.toml").modules) == ["accounts"]
    assert (repo.root / "kb/modules/billing.md").is_file()


def test_init_when_dry_run_and_module_over_budget_then_reports_outline_only_files(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    init(repo, modules=["billing"])
    config_text = (
        (repo.root / "milepost.toml")
        .read_text()
        .replace("max_source_bytes = 200000", "max_source_bytes = 40")
    )
    repo.write("milepost.toml", config_text)
    repo.write("app/billing/more.py", "def more():\n    return 1\n")
    (repo.root / "kb/modules/billing.md").unlink()

    report = init(repo, dry_run=True)

    assert report.outline_only == {"billing": ["app/billing/more.py"]}


def test_init_when_hooks_requested_then_hooks_installed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    report = run_init(
        repo.root,
        modules=None,
        dry_run=False,
        force_config=False,
        client=FakeClient(),
        embedder=HashEmbedder(),
        environ=ENV,
        now="2026-10-12T09:00:00Z",
        sleep=no_sleep,
        install_hooks_flag=True,
    )

    assert report.hooks is not None and "pre-commit" in report.hooks.written
    assert (repo.root / ".git/hooks/pre-commit").is_file()


def test_init_when_hooks_not_requested_then_no_hooks_written(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    report = init(repo)

    assert report.hooks is None
    assert not (repo.root / ".git/hooks/pre-commit").exists()


def test_init_when_mode_agent_then_scaffolds_and_skips_drafting_with_instruction(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    client = FakeClient()

    report = run_init(
        repo.root,
        modules=["billing"],
        dry_run=False,
        force_config=False,
        client=client,
        embedder=HashEmbedder(),
        environ={},
        now="2026-10-14T09:00:00Z",
        sleep=no_sleep,
    )

    config = load_config(repo.root / "milepost.toml")
    assert config.draft.mode == "agent" and list(config.modules) == ["billing"]
    assert client.calls == 0 and report.drafted == []
    assert report.agent_pending == ["billing"]
    assert not (repo.root / "kb/modules/billing.md").exists()
    assert not (repo.root / "kb/INDEX.md").exists()


def test_init_when_model_mode_requested_but_config_exists_in_agent_mode_then_usage_error(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    init(repo, modules=["billing"], model_mode=False)

    with pytest.raises(UsageError, match="drafts with Claude"):
        init(repo, model_mode=True)


def test_init_when_force_config_on_agent_mode_repo_then_agent_mode_kept(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    init(repo, modules=["billing"], model_mode=False)

    report = init(repo, modules=["billing"], force_config=True, model_mode=False)

    assert load_config(repo.root / "milepost.toml").draft.mode == "agent"
    assert report.agent_mode is True


def test_init_when_force_config_on_model_mode_repo_then_model_mode_kept(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    init(repo, modules=["billing"], model_mode=True)

    init(repo, modules=["billing"], force_config=True, model_mode=False)

    assert load_config(repo.root / "milepost.toml").draft.mode == "model"


def test_init_when_nothing_requested_then_default_mode_is_agent_and_no_key_is_needed(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    report = init(repo, modules=["billing"], model_mode=False, environ={})

    assert load_config(repo.root / "milepost.toml").draft.mode == "agent"
    assert report.agent_pending == ["billing"]


def test_init_when_model_mode_and_litellm_missing_then_fails_before_writing_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a: None if name == "litellm" else real(name, *a)
    )
    repo = make_repo(tmp_path)

    with pytest.raises(EnvironmentProblem, match=r"milepost\[model\]"):
        init(repo, modules=["billing"], model_mode=True)

    assert not (repo.root / "milepost.toml").exists()
    assert not (repo.root / "kb").exists()
