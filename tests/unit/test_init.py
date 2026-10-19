import socket
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from support.embedders import HashEmbedder
from support.kb_repo import KbRepo

from milepost.config import load_config
from milepost.errors import EnvironmentProblem, UsageError
from milepost.services.init import InitReport, run_init


def make_repo(tmp_path: Path) -> KbRepo:
    repo = KbRepo(tmp_path / "repo")
    repo.write("app/billing/api.py", "def charge(card):\n    return card\n")
    repo.write("app/accounts/models.py", "class Account:\n    pass\n")
    repo.commit("initial")
    return repo


def init(
    repo: KbRepo,
    modules: list[str] | None = None,
    dry_run: bool = False,
    force_config: bool = False,
    install_hooks_flag: bool = False,
) -> InitReport:
    return run_init(
        repo.root,
        modules=modules,
        dry_run=dry_run,
        force_config=force_config,
        embedder=HashEmbedder(),
        install_hooks_flag=install_hooks_flag,
    )


def write_note(repo: KbRepo, module_id: str, sources: list[str]) -> Path:
    repo.write_note_file(f"kb/modules/{module_id}.md", f"module/{module_id}", sources, "draft")
    return repo.root / f"kb/modules/{module_id}.md"


def test_init_when_not_git_repo_then_exit_three(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()

    with pytest.raises(EnvironmentProblem) as error:
        run_init(tmp_path, modules=None, dry_run=False, force_config=False, embedder=HashEmbedder())

    assert error.value.exit_code == 3


def test_init_when_scan_runs_then_no_module_activated_automatically(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    report = init(repo)

    config = tomllib.loads((repo.root / "milepost.toml").read_text())
    assert config.get("modules", {}) == {}
    assert "# [modules.billing]" in (repo.root / "milepost.toml").read_text()
    assert report.pending == []
    assert (repo.root / "kb").is_dir()


def test_init_when_modules_flag_then_declares_only_named_candidates_and_writes_no_notes(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    report = init(repo, modules=["billing"])

    config = load_config(repo.root / "milepost.toml")
    assert list(config.modules) == ["billing"]
    assert config.modules["billing"].sources == ["app/billing/**/*.py"]
    assert report.pending == ["billing"]
    assert not (repo.root / "kb/modules/billing.md").exists()
    assert not (repo.root / "kb/INDEX.md").exists()
    assert (repo.root / "kb/.index/index.sqlite").is_file()


def test_init_when_config_is_written_then_it_has_no_model_settings(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    init(repo, modules=["billing"])

    text = (repo.root / "milepost.toml").read_text()
    assert "[draft]" in text and "max_source_bytes" in text
    assert "mode" not in text and "provider_model" not in text and "MILEPOST_MODEL" not in text


def test_init_when_modules_flag_names_non_candidate_then_exit_two(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(UsageError) as error:
        init(repo, modules=["nonsense"])

    assert error.value.exit_code == 2
    assert not (repo.root / "milepost.toml").exists()


def test_init_when_run_twice_then_second_run_creates_nothing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    init(repo, modules=["billing"])

    second = init(repo, modules=["billing"])

    assert second.created == []


def test_init_when_note_exists_then_it_is_not_pending_and_not_overwritten(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    init(repo, modules=["billing"])
    note_path = write_note(repo, "billing", ["app/billing/**/*.py"])
    note_path.write_text(note_path.read_text() + "\nHand-written addition.\n")
    before = note_path.read_bytes()

    report = init(repo, modules=["billing"])

    assert note_path.read_bytes() == before
    assert report.pending == []


def test_init_when_config_exists_and_modules_flag_then_appends_only_new_module_tables(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    init(repo, modules=["billing"])

    report = init(repo, modules=["accounts"])

    config = load_config(repo.root / "milepost.toml")
    assert sorted(config.modules) == ["accounts", "billing"]
    assert "accounts" in report.pending


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

    report = init(repo, modules=["billing", "accounts"], dry_run=True)

    after = sorted(
        p.relative_to(repo.root).as_posix()
        for p in repo.root.rglob("*")
        if ".git/" not in p.as_posix()
    )
    assert after == before
    assert report.dry_run is True
    assert report.planned_files == {
        "billing": ["app/billing/api.py"],
        "accounts": ["app/accounts/models.py"],
    }
    assert report.estimated_tokens > 0


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


def test_init_when_run_then_gitignore_lists_only_the_index_and_keeps_other_lines(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write(".gitignore", "node_modules/\n")

    init(repo)

    assert (repo.root / ".gitignore").read_text().splitlines() == ["node_modules/", "kb/.index/"]


def test_init_when_run_then_gitattributes_has_merge_driver_line_once(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    init(repo)
    init(repo)

    text = (repo.root / ".gitattributes").read_text()
    assert text.count("kb/**/*.md merge=milepost") == 1


def test_init_when_force_config_then_config_rewritten_from_scratch(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    init(repo, modules=["billing"])
    write_note(repo, "billing", ["app/billing/**/*.py"])

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

    report = init(repo, dry_run=True)

    assert report.outline_only == {"billing": ["app/billing/more.py"]}


def test_init_when_dry_run_and_file_looks_like_a_secret_then_reports_it_withheld(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/keys.py", 'KEY = "AKIAABCDEFGHIJKLMNOP"\n')

    report = init(repo, modules=["billing"], dry_run=True)

    assert report.withheld == {"billing": ["app/billing/keys.py"]}


def test_init_when_hooks_requested_then_hooks_installed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    report = init(repo, install_hooks_flag=True)

    assert report.hooks is not None and "pre-commit" in report.hooks.written
    assert (repo.root / ".git/hooks/pre-commit").is_file()


def test_init_when_hooks_not_requested_then_no_hooks_written(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    report = init(repo)

    assert report.hooks is None
    assert not (repo.root / ".git/hooks/pre-commit").exists()
