import json
from pathlib import Path

import pytest
from support.embedders import HashEmbedder
from support.kb_repo import KbRepo

from milepost import mcp_server
from milepost.config import Config, load_config
from milepost.core.notes import read_note, write_note
from milepost.embeddings import Embedder
from milepost.errors import UsageError
from milepost.services import kb as kb_module_under_test
from milepost.services.kb import (
    KbToolError,
    kb_check,
    kb_draft_module,
    kb_file,
    kb_impact,
    kb_module,
    kb_outline,
    kb_overview,
    kb_search,
    kb_sync,
    kb_update,
)

NOW = "2026-10-13T09:00:00Z"
SOURCES = ["app/billing/**/*.py"]
BODY = "\n## Purpose\n\nBills customers.\n\n## Gotchas\n\n- Retries: `charge.py`.\n"


def embedder_for(config: Config) -> Embedder:
    return HashEmbedder()


def make_repo(tmp_path: Path, status: str = "reviewed") -> KbRepo:
    repo = KbRepo(tmp_path / "repo")
    repo.add_module(
        "billing",
        SOURCES,
        {
            "app/billing/charge.py": "def charge(card):\n    return card\n",
            "app/api/routes.py": "from app.billing.charge import charge\n",
        },
        status=status,
        body=BODY,
    )
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    return repo


def code_of(error: pytest.ExceptionInfo[KbToolError]) -> str:
    return error.value.code


def test_kb_overview_when_called_then_returns_index_and_stale_count(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    result = kb_overview(repo.root)

    assert "| billing | Bills customers. |" in result["index"]
    assert result["stale_count"] == 1
    assert result["branch"] == "main"
    assert any("stale" in step for step in result["next_steps"])


def test_kb_overview_when_note_is_draft_then_draft_count_reported(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, status="draft")

    assert kb_overview(repo.root)["draft_count"] == 1


def test_kb_overview_when_no_config_then_environment_error(tmp_path: Path) -> None:
    with pytest.raises(KbToolError) as error:
        kb_overview(tmp_path)

    assert error.value.code == "ENVIRONMENT"
    assert "/kb-init" in error.value.message


def test_kb_module_when_unknown_id_then_error_not_found(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_module(repo.root, "nope")

    assert error.value.code == "NOT_FOUND"


def test_kb_module_when_known_id_then_includes_note_hash_verify_and_related(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.add_module("accounts", ["app/accounts/**/*.py"], {"app/accounts/a.py": "x = 1\n"})
    text = (
        (repo.root / "milepost.toml")
        .read_text()
        .replace(
            f'sources = ["{SOURCES[0]}"]',
            f'sources = ["{SOURCES[0]}"]\nrelated = ["accounts"]\n'
            'verify = ["pytest tests/billing"]',
        )
    )
    (repo.root / "milepost.toml").write_text(text)

    result = kb_module(repo.root, "billing")

    assert result["id"] == "module/billing"
    assert result["source_hash_now"] == repo.hash_of(SOURCES)
    assert result["stale"] is False
    assert result["verify"] == ["pytest tests/billing"]
    assert result["related"] == [
        {"id": "module/accounts", "title": "accounts", "status": "reviewed"}
    ]
    assert "Bills customers" in result["body"]


def test_kb_module_when_draft_then_next_steps_warn(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, status="draft")

    steps = " ".join(kb_module(repo.root, "billing")["next_steps"])

    assert "is a draft" in steps and "kb_outline" in steps


def test_kb_file_when_path_matches_sources_then_returns_covering_notes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = kb_file(repo.root, "app/billing/charge.py")

    assert [n["id"] for n in result["notes"]] == ["module/billing"]
    assert result["covered"] is True


def test_kb_file_when_called_then_each_note_has_source_hash_now_and_stale_flag(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    (note,) = kb_file(repo.root, "app/billing/charge.py")["notes"]

    assert note["stale"] is True
    assert note["source_hash_now"] == repo.hash_of(SOURCES)


def test_kb_file_when_no_note_covers_path_then_says_uncovered(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/other/x.py", "x = 1\n")

    result = kb_file(repo.root, "app/other/x.py")

    assert result["covered"] is False
    assert "UNCOVERED" in result["next_steps"][0]


def test_kb_search_when_called_then_indexes_and_returns_capped_results(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = kb_search(repo.root, embedder_for, "bills customers", limit=50)

    assert result["results"][0]["note_id"] == "module/billing"
    assert len(result["results"]) <= 10


def test_kb_update_when_body_over_limit_then_rejects(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_update(repo.root, "module/billing", "x" * 20_001, repo.hash_of(SOURCES), NOW)

    assert error.value.code == "INVALID_INPUT"


def test_kb_update_when_read_hash_missing_for_l2_then_invalid_input(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_update(repo.root, "module/billing", "## Purpose\n\nx\n", None, NOW)

    assert error.value.code == "INVALID_INPUT"


def test_kb_update_when_source_changed_after_read_then_stale_read_error(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    read_hash = repo.hash_of(SOURCES)
    repo.write("app/billing/charge.py", "def charge(card):\n    return 2\n")

    with pytest.raises(KbToolError) as error:
        kb_update(repo.root, "module/billing", "## Purpose\n\nx\n", read_hash, NOW)

    assert error.value.code == "STALE_READ"


def test_kb_update_when_read_hash_matches_working_tree_then_writes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return 2\n")

    result = kb_update(
        repo.root, "module/billing", "## Purpose\n\nCharges cards.\n", repo.hash_of(SOURCES), NOW
    )

    meta = read_note(repo.root / "kb/modules/billing.md").meta
    assert "source_hash" not in meta  # nothing is stored; staleness comes from git
    assert meta["written_at"] == NOW and meta["written_by"] == "agent"
    assert result["findings"] == []
    assert kb_module(repo.root, "billing")["stale"] is False


def test_kb_update_when_reviewed_note_updated_then_status_draft_and_review_fields_removed(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    note = read_note(repo.root / "kb/modules/billing.md")
    note.meta.update(reviewed_by="Jane <j@example.com>", reviewed_at="2026-10-01T00:00:00Z")
    write_note(note, repo.root / "kb/modules/billing.md")

    kb_update(repo.root, "module/billing", "## Purpose\n\nx.\n", repo.hash_of(SOURCES), NOW)

    meta = read_note(repo.root / "kb/modules/billing.md").meta
    assert meta["status"] == "draft"
    assert "reviewed_by" not in meta and "reviewed_at" not in meta


def test_kb_update_when_purpose_changed_then_overview_shows_it_and_check_is_clean(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    kb_update(
        repo.root, "module/billing", "## Purpose\n\nNew purpose here.\n", repo.hash_of(SOURCES), NOW
    )

    assert "New purpose here." in kb_overview(repo.root)["index"]
    assert kb_check(repo.root)["ok"] is True


def test_kb_update_when_body_unchanged_and_read_hash_current_then_refreshes_hash_and_written_at(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    body = read_note(repo.root / "kb/modules/billing.md").body.strip("\n")

    kb_update(repo.root, "module/billing", body, repo.hash_of(SOURCES), NOW)

    note = read_note(repo.root / "kb/modules/billing.md")
    assert note.body.strip("\n") == body and note.meta["written_at"] == NOW


def test_kb_update_when_frontmatter_key_other_than_status_requested_then_not_changeable(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    kb_update(repo.root, "module/billing", "## Purpose\n\nx.\n", repo.hash_of(SOURCES), NOW)

    meta = read_note(repo.root / "kb/modules/billing.md").meta
    assert meta["sources"] == SOURCES and meta["id"] == "module/billing"


def test_kb_update_when_id_has_unknown_prefix_then_invalid_input(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_update(repo.root, "thing/x", "body", None, NOW)

    assert error.value.code == "INVALID_INPUT"


def test_kb_draft_module_when_module_not_in_config_then_not_found_with_config_hint(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_draft_module(repo.root, "nope")

    assert error.value.code == "NOT_FOUND" and "milepost.toml" in error.value.message


def test_kb_draft_module_when_note_exists_then_conflict(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_draft_module(repo.root, "billing")

    assert error.value.code == "CONFLICT"


def test_kb_draft_module_when_every_file_has_a_secret_then_refused_naming_file_only(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.add_module(
        "other",
        ["app/other/**/*.py"],
        {"app/other/x.py": 'KEY = "AKIAABCDEFGHIJKLMNOP"\n'},
        with_note=False,
    )
    with pytest.raises(KbToolError) as error:
        kb_draft_module(repo.root, "other")

    assert error.value.code == "INVALID_INPUT"
    assert "app/other/x.py" in error.value.message
    assert "secret_scan_allow" in error.value.message
    assert "AKIAABCDEFGHIJKLMNOP" not in error.value.message


def test_kb_check_when_called_then_findings_and_ok_flag(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    result = kb_check(repo.root)

    assert result["ok"] is True  # a stale note only warns unless [check] stale = "fail"
    stale = [f for f in result["findings"] if f["code"] == "STALE_NOTE"]
    assert stale and stale[0]["severity"] == "warning"
    assert any("stale" in step for step in result["next_steps"])


def test_kb_outline_impact_sync_when_called_then_match_services(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return None\n")

    assert kb_outline(repo.root, "app/billing/charge.py")["symbols"][0]["name"] == "charge"
    assert kb_impact(repo.root, "app/billing/charge.py")["importers"] == ["app/api/routes.py"]
    sync = kb_sync(repo.root)
    assert sync["changes"][0]["path"] == "app/billing/charge.py"
    assert sync["next_steps"][-1] == "then call kb_check"


def test_kb_outline_when_file_missing_then_not_found(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_outline(repo.root, "nope.py")

    assert error.value.code == "NOT_FOUND"


def test_tool_response_when_any_tool_called_then_next_steps_present_and_deterministic(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    calls = [
        lambda: kb_overview(repo.root),
        lambda: kb_module(repo.root, "billing"),
        lambda: kb_file(repo.root, "app/billing/charge.py"),
        lambda: kb_check(repo.root),
        lambda: kb_outline(repo.root, "app/billing/charge.py"),
        lambda: kb_impact(repo.root, "app/billing/charge.py"),
        lambda: kb_sync(repo.root),
    ]

    for call in calls:
        first, second = call(), call()
        assert "next_steps" in first and isinstance(first["next_steps"], list)
        assert first == second


def test_kb_file_when_notes_cover_path_then_next_steps_names_kb_sync(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    steps = " ".join(kb_file(repo.root, "app/billing/charge.py")["next_steps"])

    assert "kb_sync" in steps and "kb_update" in steps


@pytest.mark.parametrize(
    "note_id",
    [
        "passage/../../../escaped",
        "module/../../x",
        "file/../../x",
        "file//etc/passwd",
        "passage/..",
    ],
)
def test_kb_update_when_id_escapes_kb_dir_then_rejected_and_nothing_written(
    tmp_path: Path, note_id: str
) -> None:
    repo = make_repo(tmp_path)
    before = sorted(p for p in tmp_path.rglob("*") if p.is_file() and ".git/" not in str(p))

    with pytest.raises(KbToolError) as error:
        kb_update(repo.root, note_id, "hi", repo.hash_of(SOURCES), NOW)

    assert error.value.code in {"INVALID_INPUT", "NOT_FOUND"}
    assert sorted(p for p in tmp_path.rglob("*") if p.is_file() and ".git/" not in str(p)) == before


def test_kb_file_when_dotfile_path_then_dot_kept(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write(".github/ci.yml", "a: 1\n")

    result = kb_file(repo.root, "./.github/ci.yml")

    assert result["path"] == ".github/ci.yml"


@pytest.mark.parametrize("path", ["../outside.py", "/etc/passwd", "a/../../outside.py"])
def test_kb_file_when_path_outside_repo_then_invalid_input(tmp_path: Path, path: str) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_file(repo.root, path)

    assert error.value.code == "INVALID_INPUT"


def test_kb_draft_module_when_sources_match_no_files_then_coded_error_not_crash(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.add_module("empty", ["app/empty/**/*.py"], {}, with_note=False)

    try:
        kb_draft_module(repo.root, "empty")
    except KbToolError as error:
        assert error.code in {"INVALID_INPUT", "NOT_FOUND", "ENVIRONMENT"}


def test_kb_check_when_a_service_raises_milepost_error_then_coded_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)

    def boom(root: Path, config: Config) -> None:
        raise UsageError("git exploded")

    monkeypatch.setattr(kb_module_under_test, "run_check", boom)

    with pytest.raises(KbToolError) as error:
        kb_check(repo.root)

    assert error.value.code == "INVALID_INPUT" and "git exploded" in error.value.message


def test_kb_update_when_existing_l2_file_is_invalid_then_does_not_claim_missing(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("kb/modules/billing.md", "not a note\n")

    with pytest.raises(KbToolError) as error:
        kb_update(repo.root, "module/billing", "## Purpose\n\nx\n", repo.hash_of(SOURCES), NOW)

    assert error.value.code == "INVALID_INPUT"
    assert "kb_draft_module" not in error.value.message
    assert (repo.root / "kb/modules/billing.md").read_text() == "not a note\n"


def test_kb_module_when_body_is_long_then_returned_in_full_with_a_shorten_step(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    long_body = "\n## Purpose\n\nBills.\n\n## Gotchas\n\n" + "- a point\n" * 3000
    note = read_note(repo.root / "kb/modules/billing.md")
    note.body = long_body
    write_note(note, repo.root / "kb/modules/billing.md")

    result = kb_module(repo.root, "billing")

    assert result["body"] == long_body
    assert any("shorten" in step for step in result["next_steps"])


def test_kb_overview_when_git_missing_or_detached_then_branch_is_explicit(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.git("checkout", "-q", "--detach")

    assert "detached" in kb_overview(repo.root)["branch"]


def repo_with_undrafted_module(tmp_path: Path) -> KbRepo:
    repo = make_repo(tmp_path)
    repo.add_module(
        "other",
        ["app/other/**/*.py"],
        {"app/other/x.py": "def run():\n    return 1\n"},
        with_note=False,
    )
    return repo


def test_kb_draft_module_when_called_then_returns_packet_and_writes_nothing(
    tmp_path: Path,
) -> None:
    repo = repo_with_undrafted_module(tmp_path)
    result = kb_draft_module(repo.root, "other")

    assert "def run()" in result["sources"] and "## Purpose" in result["system_prompt"]
    assert result["source_hash_now"] == repo.hash_of(["app/other/**/*.py"])
    assert "kb_update" in " ".join(result["next_steps"])
    assert not (repo.root / "kb/modules/other.md").exists()


def test_kb_draft_module_when_one_file_has_a_secret_then_packet_withholds_it(
    tmp_path: Path,
) -> None:
    repo = repo_with_undrafted_module(tmp_path)
    repo.write("app/other/keys.py", 'KEY = "AKIAABCDEFGHIJKLMNOP"\n')

    result = kb_draft_module(repo.root, "other")

    assert result["withheld"] == ["app/other/keys.py"]
    assert "def run()" in result["sources"]
    assert "AKIAABCDEFGHIJKLMNOP" not in result["sources"]
    assert "Files withheld" in result["truncation_notice"]
    assert any("truncation_notice at the top" in step for step in result["next_steps"])


def test_kb_update_when_agent_creates_note_and_a_file_was_withheld_then_notice_is_added(
    tmp_path: Path,
) -> None:
    repo = repo_with_undrafted_module(tmp_path)
    repo.write("app/other/keys.py", 'KEY = "AKIAABCDEFGHIJKLMNOP"\n')
    packet = kb_draft_module(repo.root, "other")

    kb_update(repo.root, "module/other", "## Purpose\n\nRuns.\n", packet["source_hash_now"], NOW)

    body = (repo.root / "kb/modules/other.md").read_text()
    assert "Files withheld" in body and "`app/other/keys.py`" in body


def test_kb_update_when_declared_module_has_no_note_then_creates_draft_l2(
    tmp_path: Path,
) -> None:
    repo = repo_with_undrafted_module(tmp_path)
    packet = kb_draft_module(repo.root, "other")

    kb_update(
        repo.root, "module/other", "## Purpose\n\nRuns things.\n", packet["source_hash_now"], NOW
    )

    note = read_note(repo.root / "kb/modules/other.md")
    assert note.meta["status"] == "draft" and note.meta["written_by"] == "agent"
    assert note.meta["sources"] == ["app/other/**/*.py"]
    assert "source_hash" not in note.meta
    assert "| other | Runs things. | draft |" in kb_overview(repo.root)["index"]
    assert kb_check(repo.root)["ok"] is True


def test_kb_update_when_module_not_declared_then_rejects(tmp_path: Path) -> None:
    repo = repo_with_undrafted_module(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_update(repo.root, "module/undeclared", "## Purpose\n\nx\n", "h", NOW)

    assert error.value.code == "NOT_FOUND"


def test_kb_update_when_stale_read_hash_then_stale_read(tmp_path: Path) -> None:
    repo = repo_with_undrafted_module(tmp_path)
    packet = kb_draft_module(repo.root, "other")
    repo.write("app/other/x.py", "def run():\n    return 2\n")

    with pytest.raises(KbToolError) as error:
        kb_update(repo.root, "module/other", "## Purpose\n\nx\n", packet["source_hash_now"], NOW)

    assert error.value.code == "STALE_READ"


def test_kb_update_when_body_contains_a_credential_then_rejected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_update(
            repo.root,
            "module/billing",
            "## Purpose\n\nUses AKIAABCDEFGHIJKLMNOP to call S3.\n",
            repo.hash_of(SOURCES),
            NOW,
        )

    assert error.value.code == "INVALID_INPUT"
    assert "AKIAABCDEFGHIJKLMNOP" not in error.value.message


def test_kb_update_when_sources_truncated_then_notice_added_automatically(
    tmp_path: Path,
) -> None:
    repo = repo_with_undrafted_module(tmp_path)
    text = (repo.root / "milepost.toml").read_text()
    (repo.root / "milepost.toml").write_text(text + "\n[draft]\nmax_source_bytes = 20\n")
    repo.write("app/other/y.py", "def second():\n    return 2\n" * 5)
    packet = kb_draft_module(repo.root, "other")

    kb_update(repo.root, "module/other", "## Purpose\n\nRuns.\n", packet["source_hash_now"], NOW)

    body = read_note(repo.root / "kb/modules/other.md").body
    assert "Truncated draft" in body and "app/other/y.py" in body


def bare_repo(tmp_path: Path) -> KbRepo:
    """A git repository with source files and no milepost.toml at all."""
    repo = KbRepo(tmp_path / "bare")
    repo.write("app/charge.py", "def charge(card):\n    return card\n")
    repo.write("app/routes.py", "from app.charge import charge\n")
    repo.write("tests/test_charge.py", "from app.charge import charge\n")
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    return repo


def test_kb_outline_impact_sync_when_no_milepost_toml_then_still_work(tmp_path: Path) -> None:
    repo = bare_repo(tmp_path)
    repo.write("app/charge.py", "def charge(card):\n    return None\n")

    assert kb_outline(repo.root, "app/charge.py")["symbols"][0]["name"] == "charge"
    impact = kb_impact(repo.root, "app/charge.py")
    assert impact["importers"] == ["app/routes.py", "tests/test_charge.py"]
    assert [t["path"] for t in impact["tests"]] == ["tests/test_charge.py"]
    sync = kb_sync(repo.root)
    assert [c["path"] for c in sync["changes"]] == ["app/charge.py"]
    assert "/kb-init" in " ".join(sync["next_steps"])
    assert sync["uncovered"] == []


def test_kb_overview_when_no_milepost_toml_then_still_points_at_kb_init(tmp_path: Path) -> None:
    repo = bare_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_overview(repo.root)

    assert error.value.code == "ENVIRONMENT" and "/kb-init" in error.value.message


def test_kb_impact_when_milepost_toml_is_invalid_then_environment_error(tmp_path: Path) -> None:
    repo = bare_repo(tmp_path)
    repo.write("milepost.toml", "this is not toml [[[\n")

    with pytest.raises(KbToolError) as error:
        kb_impact(repo.root, "app/charge.py")

    assert error.value.code == "ENVIRONMENT"


def test_kb_overview_when_modules_declared_but_no_notes_then_says_to_draft(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path / "fresh")
    repo.add_module("billing", SOURCES, {"app/billing/a.py": "x = 1\n"}, with_note=False)

    result = kb_overview(repo.root)

    assert "(no note yet)" in result["index"]
    assert any("no note yet" in step and "kb_draft_module" in step for step in result["next_steps"])


@pytest.mark.parametrize(
    "note_id", ["file/app/billing/charge.py", "passage/retry-rules", "module/"]
)
def test_kb_update_when_id_is_not_a_module_note_then_invalid_input(
    tmp_path: Path, note_id: str
) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_update(repo.root, note_id, "body", repo.hash_of(SOURCES), NOW)

    assert error.value.code == "INVALID_INPUT"


def test_kb_update_when_module_not_declared_then_not_found(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_update(repo.root, "module/ghost", "body", "h", NOW)

    assert error.value.code == "NOT_FOUND"


def test_kb_module_when_code_committed_after_the_note_then_stale_with_a_reason(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/charge.py", "def charge(card):\n    return 7\n")
    repo.commit("code only")

    result = kb_module(repo.root, "billing")

    assert result["stale"] is True and "after the note was last updated" in result["stale_reason"]


def test_kb_update_when_note_was_retitled_by_a_person_then_title_is_kept(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    note = read_note(repo.root / "kb/modules/billing.md")
    note.meta["title"] = "Billing & invoicing"
    write_note(note, repo.root / "kb/modules/billing.md")

    kb_update(repo.root, "module/billing", "## Purpose\n\nx.\n", repo.hash_of(SOURCES), NOW)

    assert read_note(repo.root / "kb/modules/billing.md").meta["title"] == "Billing & invoicing"


def test_kb_search_when_no_embedder_available_then_keyword_results_still_returned(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    result = kb_search(repo.root, lambda config: None, "bills customers", limit=5)

    assert result["results"] and result["results"][0]["note_id"] == "module/billing"


def test_cached_embedders_when_extra_missing_first_then_picked_up_without_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    config = load_config(repo.root / "milepost.toml")
    cache = mcp_server._CachedEmbedders()
    monkeypatch.setattr(mcp_server, "default_embedder", lambda *args: None)
    assert cache(config) is None

    sentinel = HashEmbedder()
    monkeypatch.setattr(mcp_server, "default_embedder", lambda *args: sentinel)

    assert cache(config) is sentinel


def test_kb_update_when_agent_kept_one_notice_heading_then_only_the_missing_block_is_added(
    tmp_path: Path,
) -> None:
    repo = repo_with_undrafted_module(tmp_path)
    repo.write("app/other/keys.py", 'KEY = "AKIAABCDEFGHIJKLMNOP"\n')
    packet = kb_draft_module(repo.root, "other")
    body = "> **Files withheld.** reworded by the agent.\n\n## Purpose\n\nRuns.\n"

    kb_update(repo.root, "module/other", body, packet["source_hash_now"], NOW)

    assert (repo.root / "kb/modules/other.md").read_text().count("Files withheld") == 1


def test_kb_module_and_draft_accept_the_module_prefix_too(tmp_path: Path) -> None:
    repo = repo_with_undrafted_module(tmp_path)

    assert kb_module(repo.root, "module/billing")["id"] == "module/billing"
    assert kb_draft_module(repo.root, "module/other")["id"] == "module/other"


def test_kb_draft_module_when_large_then_parts_are_served_in_order_each_under_the_limit(
    tmp_path: Path,
) -> None:
    repo = repo_with_undrafted_module(tmp_path)
    for n in range(12):
        repo.write(f"app/other/m{n}.py", "def f():\n    return 'a long line of code'\n" * 400)
    text = (repo.root / "milepost.toml").read_text()
    (repo.root / "milepost.toml").write_text(text + "\n[draft]\nmax_source_bytes = 10000000\n")

    first = kb_draft_module(repo.root, "other")
    last = kb_draft_module(repo.root, "other", first["parts_total"])

    assert first["parts_total"] > 1 and first["part"] == 1 and "system_prompt" in first
    assert "part=2" in " ".join(first["next_steps"]) and "kb_update" not in " ".join(
        first["next_steps"]
    )
    assert "system_prompt" not in last and "kb_update" in " ".join(last["next_steps"])
    assert "files" not in last and "outline_only" not in last  # sent once, with part 1
    assert len(json.dumps(first)) < 50_000 and len(json.dumps(last)) < 50_000
    assert first["source_hash_now"] == last["source_hash_now"]


def test_kb_draft_module_when_part_out_of_range_then_invalid_input(tmp_path: Path) -> None:
    repo = repo_with_undrafted_module(tmp_path)

    for part in (0, 2, -1):
        with pytest.raises(KbToolError) as error:
            kb_draft_module(repo.root, "other", part)
        assert error.value.code == "INVALID_INPUT" and "between 1 and 1" in error.value.message


def test_kb_update_when_id_is_blank_then_invalid_input(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(KbToolError) as error:
        kb_update(repo.root, "  ", "## Purpose\n\nx\n", None, NOW)

    assert error.value.code == "INVALID_INPUT"
