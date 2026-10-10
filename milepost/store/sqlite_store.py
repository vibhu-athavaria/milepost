"""SQLite index: notes, chunks, FTS5 keyword search, sqlite-vec neighbours (SPEC 7.2)."""

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec

from milepost.store.base import ChunkRecord, Hit, NoteRecord

_HIT_COLUMNS = "c.chunk_id, c.note_id, n.level, n.status, c.heading, c.text"
_TABLES = ("chunks_vec", "chunks_fts", "chunks", "notes", "meta")
# Filler words match almost every chunk and drown out the keyword ranking, so they are dropped
# from keyword queries. The vector search still sees the whole query.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "do",
        "does",
        "did",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "where",
        "when",
        "why",
        "we",
        "you",
        "he",
        "she",
        "they",
        "i",
        "me",
        "my",
        "our",
        "your",
        "their",
        "can",
        "could",
        "should",
        "would",
        "will",
        "shall",
        "may",
        "might",
        "not",
        "no",
        "so",
        "then",
        "than",
        "there",
        "here",
        "into",
        "about",
        "over",
    ]
)


class SqliteStore:
    def __init__(self, path: Path, dim: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.dim = dim
        self.conn = sqlite3.connect(path)
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS notes (
                note_id TEXT PRIMARY KEY, level TEXT, status TEXT,
                source_hash TEXT, content_sha TEXT, indexed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id INTEGER PRIMARY KEY, note_id TEXT, heading TEXT, text TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, heading);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(embedding float[{self.dim}]);
            """
        )
        self.conn.commit()

    def reset(self) -> None:
        for table in _TABLES:
            self.conn.execute(f"DROP TABLE IF EXISTS {table}")
        self.conn.commit()
        self._create_tables()

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
        self.conn.commit()

    def note_ids(self) -> set[str]:
        return {str(row[0]) for row in self.conn.execute("SELECT note_id FROM notes")}

    def note_content_sha(self, note_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT content_sha FROM notes WHERE note_id = ?", (note_id,)
        ).fetchone()
        return None if row is None or row[0] is None else str(row[0])

    def _delete_note(self, note_id: str) -> None:
        chunk_ids = [
            row[0]
            for row in self.conn.execute(
                "SELECT chunk_id FROM chunks WHERE note_id = ?", (note_id,)
            )
        ]
        for chunk_id in chunk_ids:
            self.conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (chunk_id,))
            self.conn.execute("DELETE FROM chunks_vec WHERE rowid = ?", (chunk_id,))
        self.conn.execute("DELETE FROM chunks WHERE note_id = ?", (note_id,))
        self.conn.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))

    def delete_note(self, note_id: str) -> None:
        self._delete_note(note_id)
        self.conn.commit()

    def replace_note(self, record: NoteRecord, chunks: list[ChunkRecord]) -> None:
        self._delete_note(record.note_id)
        self.conn.execute(
            "INSERT INTO notes(note_id, level, status, source_hash, content_sha, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.note_id,
                record.level,
                record.status,
                record.source_hash,
                record.content_sha,
                datetime.now(UTC).isoformat(),
            ),
        )
        for chunk in chunks:
            cursor = self.conn.execute(
                "INSERT INTO chunks(note_id, heading, text) VALUES (?, ?, ?)",
                (record.note_id, chunk.heading, chunk.text),
            )
            chunk_id = cursor.lastrowid
            self.conn.execute(
                "INSERT INTO chunks_fts(rowid, text, heading) VALUES (?, ?, ?)",
                (chunk_id, chunk.text, chunk.heading),
            )
            self.conn.execute(
                "INSERT INTO chunks_vec(rowid, embedding) VALUES (?, ?)",
                (chunk_id, sqlite_vec.serialize_float32(chunk.embedding)),
            )
        self.conn.commit()

    def search_keyword(self, query: str, k: int, level: str | None) -> list[Hit]:
        terms = [t for t in re.findall(r"\w+", query) if t.lower() not in _STOPWORDS]
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in terms)
        sql = (
            f"SELECT {_HIT_COLUMNS} FROM chunks_fts f "
            "JOIN chunks c ON c.chunk_id = f.rowid JOIN notes n ON n.note_id = c.note_id "
            "WHERE chunks_fts MATCH ?"
        )
        params: list[object] = [expression]
        if level:
            sql += " AND n.level = ?"
            params.append(level)
        sql += " ORDER BY f.rank LIMIT ?"
        params.append(k)
        return [Hit(*row) for row in self.conn.execute(sql, params)]

    def search_vector(self, embedding: list[float], k: int, level: str | None) -> list[Hit]:
        fetch = k if level is None else max(k * 10, 100)
        neighbours = self.conn.execute(
            "SELECT rowid FROM chunks_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (sqlite_vec.serialize_float32(embedding), fetch),
        ).fetchall()
        hits: list[Hit] = []
        for (chunk_id,) in neighbours:
            row = self.conn.execute(
                f"SELECT {_HIT_COLUMNS} FROM chunks c JOIN notes n ON n.note_id = c.note_id "
                "WHERE c.chunk_id = ?",
                (chunk_id,),
            ).fetchone()
            if row is not None and (level is None or row[2] == level):
                hits.append(Hit(*row))
        return hits[:k]

    def close(self) -> None:
        self.conn.close()
