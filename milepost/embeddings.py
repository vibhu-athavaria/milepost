"""Embedding models. fastembed is imported lazily so commands that don't embed start fast."""

import importlib.util
from typing import Any, Protocol

from milepost.errors import EnvironmentProblem, InvalidConfig


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastembedEmbedder:
    def __init__(self, model_name: str, dim: int) -> None:
        self.model_name = model_name
        self.dim = dim
        self._model: Any = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._model is None:
            try:
                from fastembed import TextEmbedding
            except ImportError as error:
                raise EnvironmentProblem(
                    "meaning-based search is unavailable because fastembed could not be "
                    "imported; reinstall with `pip install 'milepost[search]'`, or use "
                    "keyword search only"
                ) from error

            self._model = TextEmbedding(self.model_name)
        vectors = [vector.tolist() for vector in self._model.embed(texts)]
        if len(vectors[0]) != self.dim:
            raise InvalidConfig(
                "index.embedding_dim",
                f"model {self.model_name} produces {len(vectors[0])}-dim vectors, "
                f"config says {self.dim}",
            )
        return [[float(x) for x in vector] for vector in vectors]


def semantic_search_available() -> bool:
    """True when the optional `search` extra (fastembed and numpy) is installed."""
    return (
        importlib.util.find_spec("fastembed") is not None
        and importlib.util.find_spec("numpy") is not None
    )


def default_embedder(model_name: str, dim: int) -> Embedder | None:
    """The local embedder, or None when the optional `search` extra is not installed.

    Without it, the notes are indexed and searched by keyword only."""
    return FastembedEmbedder(model_name, dim) if semantic_search_available() else None
