import os
import shutil
import subprocess
from pathlib import Path

import pytest
from support.kb_repo import GIT, KbRepo

from milepost.config import load_config
from milepost.core.notes import read_note, write_note
from milepost.errors import UsageError
from milepost.services.staleness import module_staleness

SOURCES = ["app/billing/**/*.py"]


def make_repo(tmp_path: Path, extra: str = "") -> KbRepo:
    repo = KbRepo(tmp_path / "repo", extra_config=extra)
    repo.add_module(
        "billing",
        SOURCES,
        {"app/billing/a.py": "a = 1\n", "app/billing/b.py": "b = 1\n"},
    )
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    return repo


def stale(repo: KbRepo) -> bool:
    config = load_config(repo.root / "milepost.toml")
    return module_staleness(repo.root, config)["billing"].stale


def touch_note(repo: KbRepo) -> None:
    note = read_note(repo.root / "kb/modules/billing.md")
    note.body = note.body + "\nMore.\n"
    write_note(note, repo.root / "kb/modules/billing.md")


def test_staleness_when_nothing_changed_then_fresh(tmp_path: Path) -> None:
    assert stale(make_repo(tmp_path)) is False


def test_staleness_when_covered_file_edited_uncommitted_then_stale(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/a.py", "a = 2\n")

    assert stale(repo) is True


def test_staleness_when_covered_file_committed_after_note_then_stale(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/a.py", "a = 2\n")
    repo.commit("code change")

    assert stale(repo) is True


def test_staleness_when_note_touched_after_the_code_then_fresh(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/a.py", "a = 2\n")
    repo.commit("code change")
    touch_note(repo)
    repo.commit("note updated")

    assert stale(repo) is False


def test_staleness_when_code_and_note_in_the_same_commit_then_fresh(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/a.py", "a = 2\n")
    touch_note(repo)
    repo.commit("both together")

    assert stale(repo) is False


def test_staleness_when_note_edited_uncommitted_along_with_code_then_fresh(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/a.py", "a = 2\n")
    touch_note(repo)

    assert stale(repo) is False


def test_staleness_when_uncovered_file_changed_then_fresh(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/other/x.py", "x = 1\n")
    repo.commit("elsewhere")

    assert stale(repo) is False


def test_staleness_when_covered_file_deleted_then_stale(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo.root / "app/billing/b.py").unlink()
    repo.commit("delete a covered file")

    assert stale(repo) is True


def test_staleness_when_ignored_path_changed_then_fresh(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/__pycache__/gen.py", "x = 1\n")
    repo.commit("generated file")

    assert stale(repo) is False


def test_staleness_when_two_branches_touch_different_files_and_the_note_then_merge_is_clean(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    for branch, name in (("pr-a", "a"), ("pr-b", "b")):
        repo.checkout("main")
        repo.checkout(branch, create=True)
        repo.write(f"app/billing/{name}.py", f"{name} = 2\n")
        note = read_note(repo.root / "kb/modules/billing.md")
        note.body = note.body + f"\nUpdated for {name}.\n" if name == "a" else note.body
        write_note(note, repo.root / "kb/modules/billing.md")
        repo.commit(branch)
    repo.checkout("main")

    repo.git("merge", "--no-edit", "pr-a")
    repo.git("merge", "--no-edit", "pr-b")  # no stored hash, so nothing to conflict on

    assert stale(repo) is True  # pr-b's code came after the note's last update


def test_staleness_when_note_does_not_exist_then_module_is_skipped(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo.root / "kb/modules/billing.md").unlink()
    repo.commit("remove note")

    assert module_staleness(repo.root, load_config(repo.root / "milepost.toml")) == {}


def test_staleness_when_not_a_git_repository_then_usage_error(tmp_path: Path) -> None:
    (tmp_path / "milepost.toml").write_text(
        '[project]\nname = "x"\n\n[modules.a]\nsources = ["a/*.py"]\n'
    )
    (tmp_path / "kb/modules").mkdir(parents=True)
    (tmp_path / "kb/modules/a.md").write_text("x")

    with pytest.raises(UsageError):
        module_staleness(tmp_path, load_config(tmp_path / "milepost.toml"))


def test_staleness_when_code_landed_from_another_branch_with_an_older_date_then_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    repo.checkout("feature", create=True)
    repo.write("app/billing/a.py", "a = 2\n")
    repo.touch_note("billing")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2030-01-01T00:00:00")
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2030-01-01T00:00:00")
    repo.commit("feature: code and note, dated later")
    repo.checkout("main")
    repo.write("app/billing/b.py", "b = 2\n")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2020-01-01T00:00:00")
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2020-01-01T00:00:00")
    repo.commit("main: code only, dated earlier")

    repo.git("merge", "--no-edit", "feature")

    assert stale(repo) is True  # b.py changed in a commit the note's last update does not include


def test_staleness_when_note_edited_and_then_more_code_edited_uncommitted_then_stale(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/a.py", "a = 2\n")
    touch_note(repo)
    note_time = (repo.root / "kb/modules/billing.md").stat().st_mtime_ns
    os.utime(repo.root / "app/billing/a.py", ns=(note_time + 5_000_000_000,) * 2)

    assert stale(repo) is True


def test_staleness_when_code_edited_and_then_the_note_uncommitted_then_fresh(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/a.py", "a = 2\n")
    code_time = (repo.root / "app/billing/a.py").stat().st_mtime_ns
    touch_note(repo)
    os.utime(repo.root / "kb/modules/billing.md", ns=(code_time + 5_000_000_000,) * 2)

    assert stale(repo) is False


def test_staleness_when_only_filter_given_then_only_those_modules_are_judged(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.add_module("other", ["app/other/**/*.py"], {"app/other/x.py": "x = 1\n"})
    repo.commit("other module")
    config = load_config(repo.root / "milepost.toml")

    assert set(module_staleness(repo.root, config, ["other"])) == {"other"}
    assert set(module_staleness(repo.root, config)) == {"billing", "other"}


def test_staleness_when_sources_glob_matches_note_files_then_notes_do_not_count_as_code(
    tmp_path: Path,
) -> None:
    repo = KbRepo(tmp_path / "repo")
    repo.add_module("docs", ["**/*.md"], {"README.md": "hello\n"})
    repo.add_module("billing", SOURCES, {"app/billing/a.py": "a = 1\n"})
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    repo.touch_note("billing")
    repo.commit("another module's note changes later")

    config = load_config(repo.root / "milepost.toml")

    assert module_staleness(repo.root, config)["docs"].stale is False


def test_staleness_when_project_lives_in_a_subdirectory_of_the_git_repo_then_still_judged(
    tmp_path: Path,
) -> None:
    top = tmp_path / "mono"
    project = KbRepo(top / "services" / "api")
    project.add_module("billing", SOURCES, {"app/billing/a.py": "a = 1\n"})
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=top, check=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=project.root, check=False)
    shutil.rmtree(project.root / ".git")
    for args in (("add", "-A"), ("commit", "-q", "-m", "base")):
        subprocess.run([*GIT, *args], cwd=top, check=True, capture_output=True)
    (project.root / "app/billing/a.py").write_text("a = 2\n")

    config = load_config(project.root / "milepost.toml")

    assert module_staleness(project.root, config)["billing"].stale is True


def test_staleness_when_clone_is_shallow_then_usage_error_asks_for_full_history(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/a.py", "a = 2\n")
    repo.commit("second commit")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{repo.root}", str(shallow)], check=True
    )

    with pytest.raises(UsageError, match="shallow"):
        module_staleness(shallow, load_config(shallow / "milepost.toml"))
