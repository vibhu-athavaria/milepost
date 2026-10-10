"""Search with the real fastembed model. Needs the model cached or network access once."""

import json
import time
from pathlib import Path

from support.kb_repo import KbRepo
from typer.testing import CliRunner

from milepost.cli import app
from milepost.config import load_config
from milepost.embeddings import FastembedEmbedder
from milepost.services.index import run_index
from milepost.services.search import search

FIXTURES = Path(__file__).parent.parent / "fixtures"
runner = CliRunner()


def embedder_for(repo: KbRepo) -> FastembedEmbedder:
    config = load_config(repo.root / "milepost.toml")
    return FastembedEmbedder(config.index.embedding_model, config.index.embedding_dim)


def build_fixture_kb(root: Path) -> KbRepo:
    repo = KbRepo(root)
    for entry in json.loads((FIXTURES / "search_kb" / "notes.json").read_text()):
        module = entry["module"]
        body = f"\n## Purpose\n\n{entry['purpose']}\n\n## Gotchas\n\n{entry['gotcha']}\n"
        repo.add_module(module, [f"src/{module}/**/*.py"], {f"src/{module}/m.py": "x\n"}, body=body)
    return repo


def test_search_when_paraphrase_then_vector_match_returns_note(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module(
        "auth",
        ["app/auth/**/*.py"],
        {"app/auth/a.py": "x\n"},
        body="\n## Gotchas\n\nAccess credentials lapse after a quarter of an hour of inactivity.\n",
    )
    repo.add_module(
        "billing",
        ["app/billing/**/*.py"],
        {"app/billing/b.py": "y\n"},
        body="\n## Gotchas\n\nAmounts are stored as integer cents.\n",
    )
    embedder = embedder_for(repo)
    config = load_config(repo.root / "milepost.toml")
    run_index(repo.root, config, embedder)

    results = search(repo.root, config, embedder, "how long until a user has to sign in again", k=3)

    assert results[0].note_id == "module/auth"


def test_fixture_kb_when_indexed_then_builds_quickly_and_answers_all_queries(
    tmp_path: Path,
) -> None:
    repo = build_fixture_kb(tmp_path)
    config = load_config(repo.root / "milepost.toml")
    embedder = embedder_for(repo)
    list(embedder.embed(["warm up the model"]))  # exclude the one-off model load from the timing

    started = time.monotonic()
    report = run_index(repo.root, config, embedder)
    elapsed = time.monotonic() - started

    assert report.indexed == 21  # 20 module notes plus the index
    assert elapsed < 30

    queries = json.loads((FIXTURES / "search_queries.json").read_text())
    misses = []
    for item in queries:
        found = [r.note_id for r in search(repo.root, config, embedder, item["query"], k=3)]
        if item["expect"] not in found:
            misses.append((item["query"], item["expect"], found))
    assert misses == []


def test_cli_when_indexed_then_search_json_returns_expected_note(tmp_path: Path) -> None:
    repo = build_fixture_kb(tmp_path)

    indexed = runner.invoke(app, ["index", "--repo", str(repo.root)])
    found = runner.invoke(
        app,
        [
            "search",
            "how do we avoid recalculating slow results",
            "--repo",
            str(repo.root),
            "--json",
        ],
    )

    assert indexed.exit_code == 0
    assert "indexed 21" in indexed.output
    assert found.exit_code == 0
    assert json.loads(found.stdout)[0]["note_id"] == "module/caching"


def test_cli_when_search_before_index_then_exit_three_with_hint(tmp_path: Path) -> None:
    repo = build_fixture_kb(tmp_path)

    result = runner.invoke(app, ["search", "anything", "--repo", str(repo.root)])

    assert result.exit_code == 3
    assert "milepost index" in result.output


def test_cli_when_level_unknown_then_exit_two(tmp_path: Path) -> None:
    repo = build_fixture_kb(tmp_path)
    runner.invoke(app, ["index", "--repo", str(repo.root)])

    result = runner.invoke(app, ["search", "x", "--repo", str(repo.root), "--level", "L9"])

    assert result.exit_code == 2
