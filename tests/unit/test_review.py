from pathlib import Path

import pytest
from support.kb_repo import KbRepo

from milepost.config import load_config
from milepost.core.notes import read_note
from milepost.errors import EnvironmentProblem, MilepostError, UsageError
from milepost.services.review import git_identity, plan_rehash, rehash_note, review_note

NOW = "2026-10-12T09:00:00Z"
SOURCES = ["app/billing/**/*.py"]


def identity(root: Path) -> str:
    return "Jane Doe <jane@example.com>"


def make_repo(tmp_path: Path, status: str = "draft") -> KbRepo:
    repo = KbRepo(tmp_path / "repo")
    repo.add_module(
        "billing",
        SOURCES,
        {"app/billing/api.py": "def charge(card):\n    return card\n"},
        status=status,
    )
    return repo


def test_review_when_draft_then_status_reviewed_and_hash_unchanged(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    before = read_note(repo.root / "kb/modules/billing.md").meta["source_hash"]

    review_note(
        repo.root, load_config(repo.root / "milepost.toml"), "module/billing", NOW, identity
    )

    meta = read_note(repo.root / "kb/modules/billing.md").meta
    assert meta["status"] == "reviewed"
    assert meta["source_hash"] == before
    assert "| reviewed |" in (repo.root / "kb/INDEX.md").read_text()


def test_review_when_run_then_records_reviewer_and_time_from_git_identity(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    review_note(
        repo.root, load_config(repo.root / "milepost.toml"), "module/billing", NOW, identity
    )

    meta = read_note(repo.root / "kb/modules/billing.md").meta
    assert meta["reviewed_by"] == "Jane Doe <jane@example.com>"
    assert meta["reviewed_at"] == NOW


def test_git_identity_when_configured_then_name_and_email(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.git("config", "user.name", "Jane Doe")
    repo.git("config", "user.email", "jane@example.com")

    assert git_identity(repo.root) == "Jane Doe <jane@example.com>"


def test_review_when_git_identity_missing_then_exit_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    with pytest.raises(EnvironmentProblem) as error:
        review_note(repo.root, load_config(repo.root / "milepost.toml"), "module/billing", NOW)

    assert error.value.exit_code == 3
    assert read_note(repo.root / "kb/modules/billing.md").meta["status"] == "draft"


def test_review_when_note_stale_then_refused_and_unchanged(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/api.py", "def charge(card):\n    return None\n")

    with pytest.raises(MilepostError, match="stale"):
        review_note(
            repo.root, load_config(repo.root / "milepost.toml"), "module/billing", NOW, identity
        )

    assert read_note(repo.root / "kb/modules/billing.md").meta["status"] == "draft"


def test_review_when_hash_conflict_then_refused_pointing_at_rehash(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.set_hash("kb/modules/billing.md", "CONFLICT")

    with pytest.raises(MilepostError, match="rehash"):
        review_note(
            repo.root, load_config(repo.root / "milepost.toml"), "module/billing", NOW, identity
        )


def test_review_when_unknown_id_then_usage_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(UsageError, match="module/nope"):
        review_note(
            repo.root, load_config(repo.root / "milepost.toml"), "module/nope", NOW, identity
        )


def test_rehash_when_conflict_then_sets_hash_and_returns_manifest(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.set_hash("kb/modules/billing.md", "CONFLICT")
    config = load_config(repo.root / "milepost.toml")

    result = rehash_note(repo.root, config, "module/billing")

    assert result.old_hash == "CONFLICT"
    assert result.new_hash == repo.hash_of(SOURCES)
    assert list(result.manifest) == ["app/billing/api.py"]
    assert read_note(repo.root / "kb/modules/billing.md").meta["source_hash"] == result.new_hash


def test_plan_rehash_when_called_then_note_not_modified(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.set_hash("kb/modules/billing.md", "CONFLICT")
    config = load_config(repo.root / "milepost.toml")

    plan_rehash(repo.root, config, "module/billing")

    assert read_note(repo.root / "kb/modules/billing.md").meta["source_hash"] == "CONFLICT"


def test_rehash_when_note_has_no_sources_then_usage_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write(
        "kb/passages/gotcha.md",
        "---\nkb_schema: 1\nid: passage/gotcha\nlevel: L4\ntitle: g\nstatus: draft\n"
        "written_by: agent\nwritten_at: '2026-10-12T09:00:00Z'\n---\n\nA point.\n",
    )

    with pytest.raises(UsageError):
        rehash_note(repo.root, load_config(repo.root / "milepost.toml"), "passage/gotcha")
