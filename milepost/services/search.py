"""`milepost search`: keyword and vector search merged by reciprocal rank fusion (SPEC 7.4)."""

from dataclasses import dataclass
from pathlib import Path

from milepost.config import Config
from milepost.embeddings import Embedder
from milepost.errors import IndexMissing, IndexRebuildRequired, UsageError
from milepost.store.base import Hit
from milepost.store.sqlite_store import SqliteStore

CANDIDATES = 20
RRF_K = 60
SNIPPET_CHARS = 300


@dataclass(frozen=True)
class SearchResult:
    note_id: str
    level: str
    heading: str
    score: float
    snippet: str
    status: str


def search(
    root: Path,
    config: Config,
    embedder: Embedder,
    query: str,
    k: int = 5,
) -> list[SearchResult]:
    if k < 1:
        raise UsageError("--k must be at least 1")
    index_path = root / config.index.path
    if not index_path.is_file():
        raise IndexMissing(f"no search index at {config.index.path}; run `milepost index`")

    store = SqliteStore(index_path, config.index.embedding_dim)
    try:
        if store.get_meta("embedding_model") not in (None, config.index.embedding_model):
            raise IndexRebuildRequired(
                "the index was built with a different embedding model; "
                "run `milepost index --rebuild`"
            )
        keyword = store.search_keyword(query, CANDIDATES, None)
        vector = store.search_vector(embedder.embed([query])[0], CANDIDATES, None)
    finally:
        store.close()

    scores: dict[int, float] = {}
    hits: dict[int, Hit] = {}
    for ranking in (keyword, vector):
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            hits[hit.chunk_id] = hit
    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:k]
    return [
        SearchResult(
            note_id=hits[i].note_id,
            level=hits[i].level,
            heading=hits[i].heading,
            score=scores[i],
            snippet=hits[i].text[:SNIPPET_CHARS],
            status=hits[i].status,
        )
        for i in ordered
    ]
