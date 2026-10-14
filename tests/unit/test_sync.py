from pathlib import Path

from support.kb_repo import KbRepo

from milepost.config import load_config
from milepost.services.sync import SyncResult, sync

SOURCES = ["app/billing/**/*.py"]
BODY = (
    "\n## Purpose\n\nBills customers.\n\n## File map\n\n- `charge.py`: charges.\n\n"
    "## Invariants\n\n- Charges never exceed the limit: `charge.py::charge`.\n\n"
    "## Gotchas\n\n- Retries are not idempotent, see `refund.py`.\n"
)


def make_repo(tmp_path: Path, extra: str = "") -> KbRepo:
    repo = KbRepo(tmp_path / "repo", extra_config=extra)
    repo.add_module(
        "billing",
        SOURCES,
        {
            "app/billing/charge.py": "def charge(card):\n    return card\n",
            "app/billing/refund.py": "def refund(card):\n    return card\n",
            "app/other/thing.py": "x = 1\n",
        },
        body=BODY,
    )
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    return repo


def run(repo: KbRepo, base: str | None = None) -> SyncResult:
    return sync(repo.root, load_config(repo.root / "milepost.toml"), base)


def test_sync_when_nothing_changed_then_empty_and_says_so(tmp_path: Path) -> None:
    result = run(make_repo(tmp_path))

    assert result.changes == []
    assert result.next_steps == ["No changed files; nothing to update."]


def test_sync_when_file_modified_in_module_then_routes_to_the_note_with_stale_flag(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    result = run(repo)

    (change,) = result.changes
    assert (change.path, change.status, change.modules) == (
        "app/billing/charge.py",
        "modified",
        ["billing"],
    )
    (note,) = change.notes
    assert (note.id, note.stale) == ("module/billing", True)
    assert note.source_hash_now == repo.hash_of(SOURCES)
    assert "re-read app/billing/charge.py" in change.routes[0]


def test_sync_when_file_added_then_routes_to_l2_file_map(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/invoice.py", "def invoice():\n    pass\n")

    (change,) = run(repo).changes

    assert change.status == "added"
    assert "File map" in change.routes[0]


def test_sync_when_file_deleted_then_routes_to_the_file_map(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo.root / "app/billing/refund.py").unlink()

    (change,) = run(repo).changes

    assert change.status == "deleted"
    assert "remove or rename app/billing/refund.py in the File map" in change.routes[0]


def test_sync_when_path_uncovered_then_uncovered_dir_guidance(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/other/thing.py", "x = 2\n")

    result = run(repo)

    assert result.uncovered == ["app/other/thing.py"]
    assert any("covered by no module" in step for step in result.next_steps)


def test_sync_when_invariant_cites_changed_file_then_bullet_named(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    result = run(repo)

    (cited,) = result.cited
    assert cited.note_id == "module/billing"
    assert cited.section == "Invariants"
    assert cited.path == "app/billing/charge.py"
    assert "Charges never exceed the limit" in cited.text
    assert any("still holds" in step for step in result.next_steps)


def test_sync_when_citation_ambiguous_then_skipped(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/sub/charge.py", "y = 1\n")
    repo.commit("second charge.py")
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    assert run(repo).cited == []


def test_sync_when_base_given_then_uses_range_not_working_tree(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.checkout("feature", create=True)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")
    repo.commit("change")

    assert run(repo).changes == []
    assert [c.path for c in run(repo, base="main").changes] == ["app/billing/charge.py"]


def test_sync_when_module_has_verify_then_commands_included(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    text = (
        (repo.root / "milepost.toml")
        .read_text()
        .replace(
            f'sources = ["{SOURCES[0]}"]',
            f'sources = ["{SOURCES[0]}"]\nverify = ["pytest tests/billing"]',
        )
    )
    (repo.root / "milepost.toml").write_text(text)
    repo.commit("verify")
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    result = run(repo)

    assert result.verify == {"billing": ["pytest tests/billing"]}
    assert "run (billing): pytest tests/billing" in result.next_steps


def test_sync_when_only_kb_files_changed_then_nothing_to_update(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("kb/modules/billing.md", (repo.root / "kb/modules/billing.md").read_text() + "x\n")

    assert run(repo).changes == []


def test_sync_when_module_has_no_note_then_suggests_drafting(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.add_module("other", ["app/other/**/*.py"], {}, with_note=False)
    repo.commit("module without note")
    repo.write("app/other/thing.py", "x = 3\n")

    (change,) = run(repo).changes

    assert any("has no note yet" in route for route in change.routes)


def test_sync_when_run_twice_then_identical(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    assert run(repo) == run(repo)


def test_sync_when_several_files_change_in_one_module_then_next_steps_has_every_route(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")
    repo.write("app/billing/invoice.py", "def invoice():\n    pass\n")
    (repo.root / "app/billing/refund.py").unlink()

    steps = " | ".join(run(repo).next_steps)

    assert "re-read app/billing/charge.py" in steps
    assert "add app/billing/invoice.py to the File map" in steps
    assert "remove or rename app/billing/refund.py in the File map" in steps


def test_sync_when_module_has_no_note_then_next_steps_says_to_draft(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.add_module("other", ["app/other/**/*.py"], {}, with_note=False)
    repo.commit("module without note")
    repo.write("app/other/thing.py", "x = 3\n")

    assert any("has no note yet" in step for step in run(repo).next_steps)


def test_sync_when_note_exists_but_is_invalid_then_not_reported_as_missing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("kb/modules/billing.md", "not a note\n")
    repo.commit("break the note")
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    result = run(repo)

    assert not any("has no note yet" in step for step in result.next_steps)


def test_sync_when_repo_has_no_commits_then_everything_counts_as_added(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path / "fresh")
    repo.add_module("billing", SOURCES, {"app/billing/a.py": "x = 1\n"}, with_note=False)

    result = run(repo)

    assert {c.status for c in result.changes} == {"added"}
    assert "app/billing/a.py" in [c.path for c in result.changes]


def test_sync_when_milepost_toml_has_no_modules_but_kb_exists_then_normal_guidance(
    tmp_path: Path,
) -> None:
    repo = KbRepo(tmp_path / "configured")
    repo.write("app/x.py", "x = 1\n")
    repo.write_config()
    repo.write("kb/modules/.keep", "")
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    repo.write("app/x.py", "x = 2\n")

    result = run(repo)

    assert result.uncovered == ["app/x.py"]
    assert not any("No knowledge base" in step for step in result.next_steps)
