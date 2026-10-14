import builtins
import importlib.util
from typing import Any

import pytest

from milepost.embeddings import FastembedEmbedder, default_embedder
from milepost.errors import EnvironmentProblem


def test_default_embedder_when_fastembed_missing_then_none(monkeypatch: pytest.MonkeyPatch) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "fastembed" else real(name, *a),
    )

    assert default_embedder("BAAI/bge-small-en-v1.5", 384) is None


def test_default_embedder_when_extras_installed_then_a_lazy_fastembed_embedder() -> None:
    embedder = default_embedder("BAAI/bge-small-en-v1.5", 384)

    assert isinstance(embedder, FastembedEmbedder)  # nothing is loaded until embed() is called


def test_embed_when_fastembed_cannot_be_imported_then_environment_error_naming_the_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "fastembed":
            raise ImportError("no wheels for this platform")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)

    with pytest.raises(EnvironmentProblem, match=r"milepost\[search\]"):
        FastembedEmbedder("BAAI/bge-small-en-v1.5", 384).embed(["text"])
