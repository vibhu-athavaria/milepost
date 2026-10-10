"""Embedders for tests: a fast deterministic one, and a wrapper that records what it embeds."""

import hashlib
import math
import re

DIM = 384


class HashEmbedder:
    """Bag-of-words hashed into DIM buckets. Texts sharing words are similar; no model needed."""

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            bucket = int(hashlib.md5(token.encode()).hexdigest()[:8], 16) % self.dim
            vector[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


class CountingEmbedder:
    """Wraps an embedder and remembers every text it was asked to embed."""

    def __init__(self, inner: HashEmbedder | None = None) -> None:
        self.inner = inner or HashEmbedder()
        self.dim = self.inner.dim
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return self.inner.embed(texts)
