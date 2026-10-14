import subprocess
import sys
from pathlib import Path

from support.kb_repo import GIT, KbRepo

from milepost.config import load_config
from milepost.core.notes import read_note, write_note
from milepost.services.staleness import module_staleness

SOURCES = ["app/billing/**/*.py"]
DRIVER = f"{sys.executable} -m milepost merge-driver %O %A %B %P"
NOTE = "kb/modules/billing.md"
BODY = "\n## Purpose\n\nBills.\n\n## Gotchas\n\n- First point.\n\n## Related\n\n- Last point.\n"


def make_repo(tmp_path: Path) -> KbRepo:
    repo = KbRepo(tmp_path / "repo")
    repo.add_module(
        "billing",
        SOURCES,
        {"app/billing/a.py": "a = 1\n", "app/billing/b.py": "b = 1\n"},
        body=BODY,
    )
    repo.write(".gitattributes", "kb/**/*.md merge=milepost\n")
    repo.git("config", "merge.milepost.driver", DRIVER)
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    return repo


def edit_branch(repo: KbRepo, branch: str, code_file: str, old: str, new: str) -> None:
    repo.checkout("main")
    repo.checkout(branch, create=True)
    repo.write(f"app/billing/{code_file}", f"{code_file[0]} = 2\n")
    note = read_note(repo.root / NOTE)
    note.body = note.body.replace(old, new)
    write_note(note, repo.root / NOTE)
    repo.commit(branch)


def merge(repo: KbRepo, branch: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*GIT, "merge", "--no-edit", branch],
        cwd=repo.root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_merge_when_two_branches_change_different_files_and_notes_then_merge_is_clean(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    edit_branch(repo, "pr-a", "a.py", "First point.", "First point, updated by A.")
    edit_branch(repo, "pr-b", "b.py", "Last point.", "Last point, updated by B.")
    repo.checkout("main")

    first = merge(repo, "pr-a")
    second = merge(repo, "pr-b")

    assert first.returncode == 0 and second.returncode == 0, second.stdout + second.stderr
    body = read_note(repo.root / NOTE).body
    assert "updated by A" in body and "updated by B" in body
    assert "<<<<<<<" not in body


def test_merge_when_prose_edited_in_same_place_then_body_markers_left(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    edit_branch(repo, "pr-a", "a.py", "First point.", "Charges cards, A.")
    edit_branch(repo, "pr-b", "b.py", "First point.", "Charges cards, B.")
    repo.checkout("main")
    merge(repo, "pr-a")

    result = merge(repo, "pr-b")

    assert result.returncode != 0
    text = (repo.root / NOTE).read_text()
    assert "<<<<<<<" in text and ">>>>>>>" in text


def test_merge_when_only_code_came_after_the_notes_last_update_then_note_is_stale(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    edit_branch(repo, "pr-a", "a.py", "First point.", "First point, updated by A.")
    repo.checkout("main")
    repo.checkout("pr-code", create=True)
    repo.write("app/billing/b.py", "b = 99\n")
    repo.commit("code only")
    repo.checkout("main")
    merge(repo, "pr-a")
    merge(repo, "pr-code")

    state = module_staleness(repo.root, load_config(repo.root / "milepost.toml"))["billing"]

    assert state.stale is True
