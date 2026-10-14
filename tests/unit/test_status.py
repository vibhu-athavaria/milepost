from pathlib import Path

import pytest
from support.kb_repo import KbRepo

from milepost.config import load_config
from milepost.core.notes import read_note, write_note
from milepost.errors import InvalidConfig
from milepost.services.status import ModuleStatus, module_statuses

SOURCES = ["app/billing/**/*.py"]


def make_repo(tmp_path: Path, extra: str = "") -> KbRepo:
    repo = KbRepo(tmp_path / "repo", extra_config=extra)
    repo.add_module(
        "billing",
        SOURCES,
        {"app/billing/charge.py": "def charge(card):\n    return card\n"},
        status="draft",
    )
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    return repo


def review(repo: KbRepo) -> None:
    note = read_note(repo.root / "kb/modules/billing.md")
    note.meta.update(
        status="reviewed", reviewed_by="Jane <j@example.com>", reviewed_at="2026-10-01T00:00:00Z"
    )
    write_note(note, repo.root / "kb/modules/billing.md")
    repo.commit("Jane reviews the billing note")


def statuses(repo: KbRepo) -> dict[str, ModuleStatus]:
    config = load_config(repo.root / "milepost.toml")
    return {s.module_id: s for s in module_statuses(repo.root, config)}


def test_status_when_note_never_reviewed_then_marked_never_reviewed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    entry = statuses(repo)["billing"]

    assert entry.never_reviewed is True and entry.note_status == "draft"


def test_status_when_note_reviewed_then_counts_lines_changed_since_baseline_commit(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    review(repo)
    repo.write("app/billing/charge.py", "def charge(card):\n    return card.amount\n    # new\n")
    repo.commit("change billing")

    entry = statuses(repo)["billing"]

    assert entry.never_reviewed is False
    assert entry.lines_changed_since == 3  # one line replaced (1 added, 1 deleted) + one added
    assert entry.commits_since == 1
    assert entry.reviewed_by == "Jane <j@example.com>"


def test_status_when_reviewed_note_later_edited_by_agent_then_baseline_is_last_reviewed_commit(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    review(repo)
    note = read_note(repo.root / "kb/modules/billing.md")
    note.meta["status"] = "draft"
    note.meta.pop("reviewed_by")
    note.meta.pop("reviewed_at")
    write_note(note, repo.root / "kb/modules/billing.md")
    repo.commit("agent edits the note")
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")
    repo.commit("code change after the review")

    entry = statuses(repo)["billing"]

    assert entry.note_status == "draft"
    assert entry.never_reviewed is False
    assert entry.commits_since == 1 and entry.lines_changed_since == 2


def test_status_when_history_squashed_then_baseline_still_found(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    review(repo)
    repo.checkout("feature", create=True)
    repo.write("app/billing/charge.py", "def charge(card):\n    return 1\n")
    repo.commit("feature work")
    repo.checkout("main")
    repo.git("merge", "--squash", "feature")
    repo.commit("squash merge of feature")

    entry = statuses(repo)["billing"]

    assert entry.never_reviewed is False and entry.commits_since == 1


def test_status_when_commits_carry_agent_trailer_then_counted_as_agent_commits(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    review(repo)
    repo.write("app/billing/charge.py", "def charge(card):\n    return 1\n")
    repo.commit("by hand")
    repo.write("app/billing/charge.py", "def charge(card):\n    return 2\n")
    repo.commit("by agent\n\nCo-Authored-By: Claude Sonnet <noreply@anthropic.com>")

    entry = statuses(repo)["billing"]

    assert entry.commits_since == 2 and entry.agent_commits_since == 1


def test_status_when_trailer_configured_then_custom_pattern_used(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, extra='\n[visibility]\nagent_trailers = ["bot-made"]\n')
    review(repo)
    repo.write("app/billing/charge.py", "def charge(card):\n    return 1\n")
    repo.commit("bot-made change")

    assert statuses(repo)["billing"].agent_commits_since == 1


def test_status_when_several_modules_then_never_reviewed_first_then_most_changed(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    review(repo)
    repo.add_module("other", ["app/other/**/*.py"], {"app/other/x.py": "x = 1\n"}, status="draft")
    repo.commit("add other")

    config = load_config(repo.root / "milepost.toml")
    order = [s.module_id for s in module_statuses(repo.root, config)]

    assert order == ["other", "billing"]


def test_config_when_agent_trailer_not_valid_regex_then_exit_two(tmp_path: Path) -> None:
    (tmp_path / "milepost.toml").write_text(
        '[project]\nname = "x"\n\n[visibility]\nagent_trailers = ["(Claude"]\n'
    )

    with pytest.raises(InvalidConfig) as error:
        load_config(tmp_path / "milepost.toml")

    assert error.value.exit_code == 2 and error.value.field_path.startswith("visibility")


def test_status_when_commit_touches_many_files_then_counted_once(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    for i in range(210):
        repo.write(f"app/billing/m{i}.py", "x = 1\n")
    repo.commit("many files")
    review(repo)
    for i in (0, 205):
        repo.write(f"app/billing/m{i}.py", "x = 2\n")
    repo.commit("touches two chunks\n\nCo-Authored-By: Claude <noreply@anthropic.com>")

    entry = statuses(repo)["billing"]

    assert entry.commits_since == 1 and entry.agent_commits_since == 1


def test_status_when_file_deleted_since_review_then_its_lines_count_as_churn(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/big.py", "".join(f"v{i} = {i}\n" for i in range(50)))
    repo.write("app/billing/keep.py", "k = 1\n")
    repo.commit("add files")
    review(repo)
    (repo.root / "app/billing/big.py").unlink()
    repo.commit("delete big.py")

    assert statuses(repo)["billing"].lines_changed_since == 50


def test_status_when_review_is_followed_by_a_typo_fix_commit_then_baseline_not_reset(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    review(repo)
    repo.write("app/billing/charge.py", "def charge(card):\n    return 1\n")
    repo.commit("code change")
    note = read_note(repo.root / "kb/modules/billing.md")
    note.body = note.body + "\nA typo fix.\n"  # status and reviewed_at unchanged
    write_note(note, repo.root / "kb/modules/billing.md")
    repo.commit("typo fix only")

    entry = statuses(repo)["billing"]

    assert entry.lines_changed_since == 2 and entry.commits_since == 1


def test_status_when_file_name_contains_glob_characters_then_still_counted(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/[id].py", "x = 1\n")
    repo.commit("bracket file")
    review(repo)
    repo.write("app/billing/[id].py", "x = 1\ny = 2\n")
    repo.commit("edit bracket file")

    assert statuses(repo)["billing"].lines_changed_since == 1


def test_status_when_message_merely_mentions_generated_with_then_not_agent_authored(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    review(repo)
    repo.write("app/billing/charge.py", "def charge(card):\n    return 1\n")
    repo.commit(
        "Update fixtures generated with faker\n\nCo-Authored-By: Claude Monet <m@example.com>"
    )

    assert statuses(repo)["billing"].agent_commits_since == 0
