import sqlite3
from pathlib import Path

import pytest
from support.embedders import CountingEmbedder
from support.kb_repo import KbRepo

from milepost.config import Config, load_config
from milepost.errors import IndexMissing, IndexRebuildRequired
from milepost.services.index import run_index
from milepost.services.search import search

AUTH_BODY = (
    "\n## Purpose\n\nHandles login sessions.\n\n"
    "## Gotchas\n\nTokens expire after fifteen minutes.\n"
)
BILLING_BODY = (
    "\n## Purpose\n\nCreates invoices and charges cards.\n\n"
    "## Invariants\n\nAmounts are integers.\n"
)


def make_repo(tmp_path: Path, extra_config: str = "") -> KbRepo:
    repo = KbRepo(tmp_path, extra_config)
    repo.add_module("auth", ["app/auth/**/*.py"], {"app/auth/a.py": "x\n"}, body=AUTH_BODY)
    repo.add_module(
        "billing", ["app/billing/**/*.py"], {"app/billing/b.py": "y\n"}, body=BILLING_BODY
    )
    return repo


def config_of(repo: KbRepo) -> Config:
    return load_config(repo.root / "milepost.toml")


def db_path(repo: KbRepo) -> Path:
    return repo.root / "kb" / ".index" / "index.sqlite"


def rows(repo: KbRepo, sql: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(db_path(repo))
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def test_index_when_fresh_then_all_notes_embedded(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    embedder = CountingEmbedder()

    report = run_index(repo.root, config_of(repo), embedder)

    assert report.indexed == 3
    assert report.skipped == 0
    assert sorted(r[0] for r in rows(repo, "select note_id from notes")) == [
        "index",
        "module/auth",
        "module/billing",
    ]
    chunk_count = rows(repo, "select count(*) from chunks")[0][0]
    assert chunk_count == len(embedder.texts) == 6  # 2 index rows + 2 auth + 2 billing sections


def test_index_when_note_unchanged_then_not_reembedded(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    run_index(repo.root, config_of(repo), CountingEmbedder())
    second = CountingEmbedder()

    report = run_index(repo.root, config_of(repo), second)

    assert second.texts == []
    assert report.indexed == 0
    assert report.skipped == 3


def test_index_when_note_edited_then_only_that_note_reembedded(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    run_index(repo.root, config_of(repo), CountingEmbedder())
    note = repo.root / "kb" / "modules" / "auth.md"
    note.write_text(note.read_text() + "\n## Related modules\n\n- billing\n")
    second = CountingEmbedder()

    report = run_index(repo.root, config_of(repo), second)

    assert report.indexed == 1
    assert len(second.texts) == 3  # the three sections of the edited auth note
    assert all("billing" not in text or "Related" in text for text in second.texts)


def test_index_when_note_deleted_then_removed_from_index(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    run_index(repo.root, config_of(repo), CountingEmbedder())
    (repo.root / "kb" / "modules" / "billing.md").unlink()

    report = run_index(repo.root, config_of(repo), CountingEmbedder())

    assert report.removed == 1
    assert "module/billing" not in [r[0] for r in rows(repo, "select note_id from notes")]
    assert rows(repo, "select count(*) from chunks where note_id = 'module/billing'")[0][0] == 0


def test_index_when_note_invalid_then_skipped_and_reported(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("kb/modules/broken.md", "no frontmatter\n")

    report = run_index(repo.root, config_of(repo), CountingEmbedder())

    assert report.skipped_invalid == ["kb/modules/broken.md"]
    assert report.indexed == 3


def test_index_when_model_changed_then_requires_rebuild_and_fails_without_it(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    run_index(repo.root, config_of(repo), CountingEmbedder())
    repo.extra_config = '\n[index]\nembedding_model = "some/other-model"\n'
    repo.write_config()

    with pytest.raises(IndexRebuildRequired) as error:
        run_index(repo.root, config_of(repo), CountingEmbedder())
    assert "--rebuild" in str(error.value)

    report = run_index(repo.root, config_of(repo), CountingEmbedder(), rebuild=True)
    assert report.indexed == 3


def test_index_rebuild_when_run_then_tables_recreated(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    run_index(repo.root, config_of(repo), CountingEmbedder())
    connection = sqlite3.connect(db_path(repo))
    connection.execute("insert into notes(note_id, level) values ('ghost', 'L2')")
    connection.commit()
    connection.close()
    embedder = CountingEmbedder()

    report = run_index(repo.root, config_of(repo), embedder, rebuild=True)

    assert report.indexed == 3
    assert len(embedder.texts) == 6
    assert "ghost" not in [r[0] for r in rows(repo, "select note_id from notes")]


def test_index_when_run_then_no_index_md_is_written(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    run_index(repo.root, config_of(repo), CountingEmbedder())

    assert not (repo.root / "kb/INDEX.md").exists()


def indexed_repo(tmp_path: Path) -> tuple[KbRepo, CountingEmbedder]:
    repo = make_repo(tmp_path)
    embedder = CountingEmbedder()
    run_index(repo.root, config_of(repo), embedder)
    return repo, embedder


def test_search_when_keyword_present_then_note_ranks_in_results(tmp_path: Path) -> None:
    repo, embedder = indexed_repo(tmp_path)

    results = search(repo.root, config_of(repo), embedder, "fifteen minutes", k=3)

    assert results[0].note_id == "module/auth"
    assert results[0].heading == "Gotchas"
    assert results[0].status == "reviewed"
    assert len(results[0].snippet) <= 300


def test_search_when_query_has_punctuation_then_no_syntax_error(tmp_path: Path) -> None:
    repo, embedder = indexed_repo(tmp_path)

    results = search(repo.root, config_of(repo), embedder, 'tokens (expire) "after" AND -x*', k=3)

    assert results


def test_search_when_k_given_then_at_most_k_results(tmp_path: Path) -> None:
    repo, embedder = indexed_repo(tmp_path)

    assert len(search(repo.root, config_of(repo), embedder, "tokens invoices", k=2)) == 2


def test_search_when_index_missing_then_raises_with_hint_and_exit_three(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(IndexMissing) as error:
        search(repo.root, config_of(repo), CountingEmbedder(), "anything")

    assert error.value.exit_code == 3
    assert "milepost index" in str(error.value)


def test_search_when_no_embedder_then_keyword_only_and_still_finds_the_note(tmp_path: Path) -> None:
    repo, _ = indexed_repo(tmp_path)

    run_index(repo.root, config_of(repo), None, rebuild=True)
    results = search(repo.root, config_of(repo), None, "billing", k=5)

    assert results and results[0].note_id
    assert rows(repo, "select count(*) from chunk_vectors") == [(0,)]


def test_index_when_extra_arrives_after_a_keyword_only_index_then_rebuilt_with_vectors(
    tmp_path: Path,
) -> None:
    repo, embedder = indexed_repo(tmp_path)
    run_index(repo.root, config_of(repo), None, rebuild=True)
    assert rows(repo, "select count(*) from chunk_vectors") == [(0,)]

    run_index(repo.root, config_of(repo), embedder)

    assert rows(repo, "select count(*) from chunk_vectors")[0][0] > 0


def test_index_when_run_without_the_extra_after_a_semantic_index_then_vectors_are_kept(
    tmp_path: Path,
) -> None:
    repo, _ = indexed_repo(tmp_path)
    before = rows(repo, "select count(*) from chunk_vectors")

    run_index(repo.root, config_of(repo), None)

    assert rows(repo, "select count(*) from chunk_vectors") == before


def test_index_when_note_changes_without_the_extra_then_state_is_mixed_and_next_run_rebuilds(
    tmp_path: Path,
) -> None:
    repo, embedder = indexed_repo(tmp_path)
    repo.touch_note("auth")
    run_index(repo.root, config_of(repo), None)
    assert rows(repo, "select value from meta where key = 'vectors'") == [("mixed",)]

    run_index(repo.root, config_of(repo), embedder)

    assert rows(repo, "select value from meta where key = 'vectors'") == [("True",)]


def test_search_when_index_is_keyword_only_then_the_query_is_not_embedded(tmp_path: Path) -> None:
    repo, _ = indexed_repo(tmp_path)
    run_index(repo.root, config_of(repo), None, rebuild=True)
    counting = CountingEmbedder()

    search(repo.root, config_of(repo), counting, "billing", k=3)

    assert counting.texts == []
