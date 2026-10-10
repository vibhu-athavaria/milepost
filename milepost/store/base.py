"""The index storage interface (SPEC section 15). SQLite is the only v1 backend."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NoteRecord:
    note_id: str
    level: str
    status: str
    source_hash: str
    content_sha: str


@dataclass(frozen=True)
class ChunkRecord:
    heading: str
    text: str
    embedding: list[float]


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    note_id: str
    level: str
    status: str
    heading: str
    text: str


class IndexStore(Protocol):
    def get_meta(self, key: str) -> str | None: ...

    def set_meta(self, key: str, value: str) -> None: ...

    def reset(self) -> None: ...

    def note_ids(self) -> set[str]: ...

    def note_content_sha(self, note_id: str) -> str | None: ...

    def replace_note(self, record: NoteRecord, chunks: list[ChunkRecord]) -> None: ...

    def delete_note(self, note_id: str) -> None: ...

    def search_keyword(self, query: str, k: int, level: str | None) -> list[Hit]: ...

    def search_vector(self, embedding: list[float], k: int, level: str | None) -> list[Hit]: ...

    def close(self) -> None: ...
