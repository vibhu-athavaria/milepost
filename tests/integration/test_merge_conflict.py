import subprocess
import sys
from pathlib import Path

from support.kb_repo import GIT, KbRepo

from milepost.config import load_config
from milepost.core.notes import read_note, write_note
from milepost.services.check import run_check
from milepost.services.review import rehash_note

SOURCES = ["app/billing/**/*.py"]
DRIVER = f"{sys.executable} -m milepost merge-driver %O %A %B %P"


def make_repo(tmp_path: Path) -> KbRepo:
    repo = KbRepo(tmp_path / "repo")
    repo.add_module(
        "billing",
        SOURCES,
        {"app/billing/api.py": "def charge(card):\n    return card\n"},
    )
    repo.write(".gitattributes", "kb/**/*.md merge=milepost\n")
    repo.git("config", "merge.milepost.driver", DRIVER)
    repo.commit("base")
    return repo


def edit_branch(repo: KbRepo, branch: str, code: str, line: str) -> None:
    repo.checkout(branch, create=True)
    repo.write("app/billing/api.py", code)
    note = read_note(repo.root / "kb/modules/billing.md")
    note.body = note.body.replace("Describes the thing.", line)
    note.meta["source_hash"] = repo.hash_of(SOURCES)
    write_note(note, repo.root / "kb/modules/billing.md")
    repo.commit(branch)


def merge(repo: KbRepo, branch: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*GIT, "merge", "--no-edit", branch],
        cwd=repo.root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_merge_conflict_when_two_branches_edit_same_module_then_check_fails_until_rehash(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    edit_branch(repo, "feature-a", "def charge(card):\n    return card.a\n", "Describes the thing.")
    repo.checkout("main")
    edit_branch(repo, "feature-b", "def charge(card):\n    return card.b\n", "Describes the thing.")
    # feature-b's code edit collides with feature-a's; resolve the code, keep both notes' hashes
    result = merge(repo, "feature-a")
    assert result.returncode != 0  # the code file conflicts, as it would in any real merge
    repo.write("app/billing/api.py", "def charge(card):\n    return card.merged\n")
    repo.git("add", "-A")
    done = subprocess.run(
        [*GIT, "commit", "-q", "--no-edit"], cwd=repo.root, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr

    note = read_note(repo.root / "kb/modules/billing.md")
    assert note.meta["source_hash"] == "CONFLICT"
    config = load_config(repo.root / "milepost.toml")
    codes = {finding.code for finding in run_check(repo.root, config).findings}
    assert "SOURCE_HASH_CONFLICT" in codes

    rehash_note(repo.root, config, "module/billing")

    after = {f.code for f in run_check(repo.root, config).findings if f.severity == "failure"}
    assert after == set()


def test_merge_conflict_when_prose_edited_in_same_place_then_body_markers_left(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    edit_branch(repo, "feature-a", "def charge(card):\n    return card\n", "Charges cards, A.")
    repo.checkout("main")
    edit_branch(repo, "feature-b", "def charge(card):\n    return card\n", "Charges cards, B.")

    result = merge(repo, "feature-a")

    assert result.returncode != 0
    text = (repo.root / "kb/modules/billing.md").read_text()
    assert "<<<<<<<" in text and ">>>>>>>" in text
