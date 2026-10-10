"""Embedding models. fastembed is imported lazily so commands that don't embed start fast."""

from typing import Any, Protocol

from milepost.errors import InvalidConfig


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
            from fastembed import TextEmbedding

            self._model = TextEmbedding(self.model_name)
        vectors = [vector.tolist() for vector in self._model.embed(texts)]
        if len(vectors[0]) != self.dim:
            raise InvalidConfig(
                "index.embedding_dim",
                f"model {self.model_name} produces {len(vectors[0])}-dim vectors, "
                f"config says {self.dim}",
            )
        return [[float(x) for x in vector] for vector in vectors]
