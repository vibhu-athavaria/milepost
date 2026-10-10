from pathlib import Path

from milepost.store.base import ChunkRecord, NoteRecord
from milepost.store.sqlite_store import SqliteStore

DIM = 4


def store_with(tmp_path: Path, texts: dict[str, str]) -> SqliteStore:
    store = SqliteStore(tmp_path / "index.sqlite", DIM)
    for note_id, text in texts.items():
        record = NoteRecord(note_id, "L2", "reviewed", "", f"sha-{note_id}")
        store.replace_note(record, [ChunkRecord("Purpose", text, [1.0, 0.0, 0.0, 0.0])])
    return store


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
