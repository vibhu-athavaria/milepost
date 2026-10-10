import sqlite3
from pathlib import Path
from typing import Any

import pytest

from milepost.store import sqlite_store
from milepost.store.base import ChunkRecord, NoteRecord
from milepost.store.sqlite_store import SqliteStore

DIM = 4


def store_with(tmp_path: Path, texts: dict[str, str]) -> SqliteStore:
    store = SqliteStore(tmp_path / "index.sqlite", DIM)
    for note_id, text in texts.items():
        record = NoteRecord(note_id, "L2", "reviewed", "", f"sha-{note_id}")
        store.replace_note(record, [ChunkRecord("Purpose", text, [1.0, 0.0, 0.0, 0.0])])
    return store


def vector_store(tmp_path: Path, vectors: dict[str, list[float]], level: str = "L2") -> SqliteStore:
    store = SqliteStore(tmp_path / "index.sqlite", DIM)
    for note_id, vector in vectors.items():
        record = NoteRecord(note_id, level, "reviewed", "", f"sha-{note_id}")
        store.replace_note(record, [ChunkRecord("Purpose", f"text of {note_id}", vector)])
    return store


class NoExtensionLoading:
    """A real connection that, like some Python builds, has no enable_load_extension."""

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        if name in {"enable_load_extension", "load_extension"}:
            raise AttributeError(f"'sqlite3.Connection' object has no attribute '{name}'")
        return getattr(self._inner, name)


def test_store_when_sqlite_build_cannot_load_extensions_then_still_indexes_and_searches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        sqlite_store.sqlite3,
        "connect",
        lambda *args, **kwargs: NoExtensionLoading(real_connect(*args, **kwargs)),
    )

    store = store_with(tmp_path, {"billing": "charges payment cards"})

    assert [hit.note_id for hit in store.search_keyword("payment", 5, None)] == ["billing"]
    assert [hit.note_id for hit in store.search_vector([1.0, 0.0, 0.0, 0.0], 5, None)] == [
        "billing"
    ]


def test_search_vector_when_several_notes_then_nearest_first(tmp_path: Path) -> None:
    store = vector_store(
        tmp_path,
        {"far": [0.0, 1.0, 0.0, 0.0], "near": [0.9, 0.1, 0.0, 0.0], "mid": [0.5, 0.5, 0.0, 0.0]},
    )

    hits = store.search_vector([1.0, 0.0, 0.0, 0.0], 3, None)

    assert [hit.note_id for hit in hits] == ["near", "mid", "far"]


def test_search_vector_when_vectors_have_different_lengths_then_ranked_by_angle_not_size(
    tmp_path: Path,
) -> None:
    # A raw dot product would rank "big" first (3 vs 1); cosine similarity ranks "aligned" first.
    store = vector_store(tmp_path, {"big": [3.0, 3.0, 0.0, 0.0], "aligned": [1.0, 0.2, 0.0, 0.0]})

    hits = store.search_vector([1.0, 0.0, 0.0, 0.0], 2, None)

    assert [hit.note_id for hit in hits] == ["aligned", "big"]


def test_search_vector_when_k_smaller_than_notes_then_returns_k(tmp_path: Path) -> None:
    store = vector_store(
        tmp_path, {name: [1.0, float(i), 0.0, 0.0] for i, name in enumerate("abcde")}
    )

    assert len(store.search_vector([1.0, 0.0, 0.0, 0.0], 2, None)) == 2


def test_search_vector_when_level_filter_then_only_that_level(tmp_path: Path) -> None:
    store = vector_store(tmp_path, {"index": [1.0, 0.0, 0.0, 0.0]}, level="L1")
    record = NoteRecord("module/x", "L2", "reviewed", "", "sha-x")
    store.replace_note(record, [ChunkRecord("Purpose", "text", [0.9, 0.1, 0.0, 0.0])])

    only_l2 = store.search_vector([1.0, 0.0, 0.0, 0.0], 5, "L2")

    assert [hit.note_id for hit in only_l2] == ["module/x"]


def test_search_vector_when_store_empty_then_no_hits(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "index.sqlite", DIM)

    assert store.search_vector([1.0, 0.0, 0.0, 0.0], 5, None) == []


def test_search_vector_when_note_replaced_then_old_vectors_gone(tmp_path: Path) -> None:
    store = vector_store(tmp_path, {"a": [1.0, 0.0, 0.0, 0.0]})
    record = NoteRecord("a", "L2", "reviewed", "", "sha-new")
    store.replace_note(record, [ChunkRecord("Purpose", "new text", [0.0, 1.0, 0.0, 0.0])])

    hits = store.search_vector([1.0, 0.0, 0.0, 0.0], 5, None)

    assert [hit.text for hit in hits] == ["new text"]


def test_replace_note_when_embedding_has_wrong_dimension_then_raises(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "index.sqlite", DIM)
    record = NoteRecord("a", "L2", "reviewed", "", "sha")

    with pytest.raises(ValueError, match="dimension"):
        store.replace_note(record, [ChunkRecord("Purpose", "t", [1.0, 0.0])])


def test_search_keyword_when_query_has_only_stopwords_then_no_hits(tmp_path: Path) -> None:
    store = store_with(tmp_path, {"a": "the cat and the dog went to the park"})

    assert store.search_keyword("how do we and the to", 10, None) == []


def test_search_keyword_when_stopwords_shared_with_irrelevant_chunk_then_only_content_match(
    tmp_path: Path,
) -> None:
    store = store_with(
        tmp_path,
        {
            "noise": "the cat and the dog went to the park and then a walk from the lake",
            "billing": "charges payment cards",
        },
    )

    hits = store.search_keyword("how do we take a payment from the card and then", 10, None)

    assert [hit.note_id for hit in hits] == ["billing"]


def test_search_keyword_when_content_word_present_then_found(tmp_path: Path) -> None:
    store = store_with(tmp_path, {"billing": "charges payment cards", "other": "unrelated words"})

    assert [hit.note_id for hit in store.search_keyword("payment", 10, None)] == ["billing"]
