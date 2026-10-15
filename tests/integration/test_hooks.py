import os
import stat
import subprocess
from pathlib import Path

import pytest
from support.kb_repo import KbRepo

from milepost.services.hooks import (
    MARKER,
    MERGE_DRIVER,
    install_hooks,
    outdated_hooks,
    uninstall_hooks,
)


def make_repo(tmp_path: Path) -> KbRepo:
    return KbRepo(tmp_path / "repo")


def hook_path(repo: KbRepo, name: str) -> Path:
    return repo.root / ".git" / "hooks" / name


def run_hook(repo: KbRepo, name: str, fake_bin: Path | None) -> subprocess.CompletedProcess[str]:
    if not (repo.root / "milepost.toml").exists():
        (repo.root / "milepost.toml").write_text('[project]\nname = "x"\n')
    env = dict(os.environ)
    base = "/usr/bin:/bin"
    env["PATH"] = f"{fake_bin}:{base}" if fake_bin else base
    return subprocess.run(
        ["sh", str(hook_path(repo, name))], cwd=repo.root, env=env, capture_output=True, text=True
    )


def fake_milepost(tmp_path: Path, exit_code: int) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "milepost"
    script.write_text(f'#!/bin/sh\necho fake milepost "$@" >&2\nexit {exit_code}\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def test_hooks_install_when_fresh_repo_then_hooks_written_with_marker(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    report = install_hooks(repo.root)

    assert sorted(report.written) == ["post-checkout", "post-merge", "pre-commit"]
    for name in report.written:
        text = hook_path(repo, name).read_text()
        assert MARKER in text
        assert os.access(hook_path(repo, name), os.X_OK)


def test_hooks_install_when_run_then_merge_driver_configured_and_attribute_written(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    install_hooks(repo.root)

    assert repo.git("config", "merge.milepost.driver").strip() == MERGE_DRIVER
    assert (repo.root / ".gitattributes").read_text().count("kb/**/*.md merge=milepost") == 1


def test_hooks_install_when_run_twice_then_same_result(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    install_hooks(repo.root)
    first = hook_path(repo, "pre-commit").read_text()

    report = install_hooks(repo.root)

    assert hook_path(repo, "pre-commit").read_text() == first
    assert report.skipped_reason == ""
    assert (repo.root / ".gitattributes").read_text().count("merge=milepost") == 1


def test_hooks_install_when_foreign_hook_exists_then_prints_snippet_and_writes_nothing(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    hook_path(repo, "pre-commit").parent.mkdir(parents=True, exist_ok=True)
    hook_path(repo, "pre-commit").write_text("#!/bin/sh\necho mine\n")

    report = install_hooks(repo.root)

    assert report.written == []
    assert "pre-commit" in report.skipped_reason
    assert "milepost check" in report.snippet
    assert not hook_path(repo, "post-merge").exists()
    assert hook_path(repo, "pre-commit").read_text() == "#!/bin/sh\necho mine\n"


def test_hooks_install_when_hooks_path_configured_then_snippet_and_nothing_written(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.git("config", "core.hooksPath", ".husky")

    report = install_hooks(repo.root)

    assert report.written == []
    assert "core.hooksPath" in report.skipped_reason
    assert not hook_path(repo, "post-merge").exists()


def test_hooks_uninstall_when_marker_missing_then_file_untouched(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    hook_path(repo, "pre-commit").parent.mkdir(parents=True, exist_ok=True)
    hook_path(repo, "pre-commit").write_text("#!/bin/sh\necho mine\n")

    removed = uninstall_hooks(repo.root)

    assert removed == []
    assert hook_path(repo, "pre-commit").read_text() == "#!/bin/sh\necho mine\n"


def test_hooks_uninstall_when_installed_then_removed_and_driver_unset(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    install_hooks(repo.root)

    removed = uninstall_hooks(repo.root)

    assert sorted(removed) == ["post-checkout", "post-merge", "pre-commit"]
    assert not hook_path(repo, "pre-commit").exists()
    done = subprocess.run(
        ["git", "config", "merge.milepost.driver"], cwd=repo.root, capture_output=True, text=True
    )
    assert done.stdout.strip() == ""


def test_post_merge_when_index_fails_then_hook_exits_zero_with_warning(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    install_hooks(repo.root)

    done = run_hook(repo, "post-merge", fake_milepost(tmp_path, exit_code=1))

    assert done.returncode == 0
    assert "index failed" in done.stderr


def test_pre_commit_when_check_fails_then_hook_blocks(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    install_hooks(repo.root)

    done = run_hook(repo, "pre-commit", fake_milepost(tmp_path, exit_code=1))

    assert done.returncode == 1


def test_pre_commit_when_milepost_not_installed_then_hook_exits_zero_with_warning(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    install_hooks(repo.root)

    done = run_hook(repo, "pre-commit", fake_bin=None)

    assert done.returncode == 0
    assert "not installed" in done.stderr


def test_pre_commit_when_installed_then_runs_check_without_the_slow_churn_warning(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    install_hooks(repo.root)

    assert "milepost check --no-churn" in hook_path(repo, "pre-commit").read_text()


def test_outdated_hooks_when_pre_commit_written_by_an_older_milepost_then_reported(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    install_hooks(repo.root)
    assert outdated_hooks(repo.root) == []
    path = hook_path(repo, "pre-commit")
    path.write_text(path.read_text().replace(" --no-churn", ""))

    assert outdated_hooks(repo.root) == ["pre-commit"]


def test_hooks_when_repo_has_no_milepost_toml_then_they_do_nothing_and_never_call_milepost(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    install_hooks(repo.root)
    bin_dir = fake_milepost(tmp_path, exit_code=1)  # would fail loudly if it were called

    for name in ("pre-commit", "post-merge", "post-checkout"):
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
        done = subprocess.run(
            ["sh", str(hook_path(repo, name))],
            cwd=repo.root,
            env=env,
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0 and done.stderr == "", name


def test_install_when_hooks_path_set_then_snippet_shows_the_milepost_commands(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=repo.root, check=True)

    report = install_hooks(repo.root)

    assert "post-merge: milepost index" in report.snippet
    assert "pre-commit: exec milepost check --no-churn" in report.snippet
    assert "exit 0" not in report.snippet


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_hooks_when_milepost_disabled_then_they_do_nothing(tmp_path: Path, value: str) -> None:
    repo = make_repo(tmp_path)
    install_hooks(repo.root)
    (repo.root / "milepost.toml").write_text('[project]\nname = "x"\n')
    bin_dir = fake_milepost(tmp_path, exit_code=1)

    for name in ("pre-commit", "post-merge", "post-checkout"):
        env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "MILEPOST_DISABLED": value}
        done = subprocess.run(
            ["sh", str(hook_path(repo, name))],
            cwd=repo.root,
            env=env,
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0 and done.stderr == "", (name, value)
