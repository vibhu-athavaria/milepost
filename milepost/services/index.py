"""`milepost index`: keep the local search index current (SPEC section 7)."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from milepost.config import Config
from milepost.core.notes import expected_id, parse_note
from milepost.embeddings import Embedder
from milepost.errors import IndexRebuildRequired, NoteInvalid
from milepost.services.check import NOTE_DIRS
from milepost.services.chunking import Chunk, chunk_index, chunk_note
from milepost.services.render import render_index
from milepost.store.base import ChunkRecord, IndexStore, NoteRecord
from milepost.store.sqlite_store import SqliteStore

INDEX_NOTE_ID = "index"


@dataclass
class IndexReport:
    indexed: int = 0
    skipped: int = 0
    removed: int = 0
    skipped_invalid: list[str] = field(default_factory=list)


@dataclass
class _Document:
    record: NoteRecord
    chunks: list[Chunk]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _documents(root: Path, config: Config, report: IndexReport) -> list[_Document]:
    kb = root / config.project.kb_dir
    index_text = render_index(root, config)
    documents = [
        _Document(
            NoteRecord(INDEX_NOTE_ID, "L1", "", "", _sha(index_text.encode())),
            chunk_index(index_text),
        )
    ]
    for sub in NOTE_DIRS:
        for path in sorted((kb / sub).rglob("*.md")):
            rel = path.relative_to(kb).as_posix()
            data = path.read_bytes()
            try:
                note = parse_note(data.decode("utf-8"))
            except NoteInvalid:
                report.skipped_invalid.append(f"{config.project.kb_dir}/{rel}")
                continue
            meta = note.meta
            record = NoteRecord(
                note_id=str(meta.get("id") or expected_id(rel) or rel),
                level="L2",
                status=str(meta.get("status", "")),
                source_hash="",
                content_sha=_sha(data),
            )
            documents.append(_Document(record, chunk_note(note)))
    return documents


def _check_model(store: IndexStore, config: Config, rebuild: bool) -> None:
    wanted = {
        "embedding_model": config.index.embedding_model,
        "embedding_dim": str(config.index.embedding_dim),
    }
    stored = {key: store.get_meta(key) for key in wanted}
    if rebuild:
        store.reset()
    elif any(stored[key] not in (None, wanted[key]) for key in wanted):
        raise IndexRebuildRequired(
            "the index was built with a different embedding model or dimension "
            f"({stored['embedding_model']}, {stored['embedding_dim']}); "
            "run `milepost index --rebuild`"
        )
    for key, value in wanted.items():
        store.set_meta(key, value)


def run_index(root: Path, config: Config, embedder: Embedder, rebuild: bool = False) -> IndexReport:
    report = IndexReport()
    store = SqliteStore(root / config.index.path, config.index.embedding_dim)
    try:
        _check_model(store, config, rebuild)
        documents = _documents(root, config, report)
        for document in documents:
            record = document.record
            if store.note_content_sha(record.note_id) == record.content_sha:
                report.skipped += 1
                continue
            vectors = embedder.embed([chunk.text for chunk in document.chunks])
            chunks = [
                ChunkRecord(chunk.heading, chunk.text, vector)
                for chunk, vector in zip(document.chunks, vectors, strict=True)
            ]
            store.replace_note(record, chunks)
            report.indexed += 1
        current = {document.record.note_id for document in documents}
        for gone in store.note_ids() - current:
            store.delete_note(gone)
            report.removed += 1
    finally:
        store.close()
    return report
