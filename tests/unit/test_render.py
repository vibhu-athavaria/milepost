from pathlib import Path

from support.kb_repo import KbRepo

from kbmap.config import load_config
from kbmap.services.render import render_index


def test_render_index_when_modules_declared_then_rows_sorted_with_status_from_notes(
    tmp_path: Path,
) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module("services", ["app/services/**/*.py"], {"app/services/a.py": "x\n"})
    repo.add_module("ai", ["app/ai/**/*.py"], {"app/ai/b.py": "y\n"}, status="draft")

    text = render_index(repo.root, load_config(repo.root / "kbmap.toml"))

    assert text == (
        "# Codebase index\n"
        "\n"
        "| Module | Title | Status | Note |\n"
        "|---|---|---|---|\n"
        "| ai | ai | draft | kb/modules/ai.md |\n"
        "| services | services | reviewed | kb/modules/services.md |\n"
    )


def test_render_index_when_module_has_no_note_then_status_missing(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module("services", ["app/**/*.py"], {"app/a.py": "x\n"}, with_note=False)

    text = render_index(repo.root, load_config(repo.root / "kbmap.toml"))

    assert "| services | services | missing | kb/modules/services.md |" in text


def test_render_index_when_rendered_twice_then_identical(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module("services", ["app/**/*.py"], {"app/a.py": "x\n"})
    config = load_config(repo.root / "kbmap.toml")

    assert render_index(repo.root, config) == render_index(repo.root, config)
