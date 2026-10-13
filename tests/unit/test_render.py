from pathlib import Path

from support.kb_repo import KbRepo

from milepost.config import load_config
from milepost.services.render import render_index


def test_render_index_when_modules_declared_then_rows_sorted_with_status_from_notes(
    tmp_path: Path,
) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module("services", ["app/services/**/*.py"], {"app/services/a.py": "x\n"})
    repo.add_module("ai", ["app/ai/**/*.py"], {"app/ai/b.py": "y\n"}, status="draft")

    text = render_index(repo.root, load_config(repo.root / "milepost.toml"))

    assert text == (
        "# Codebase index\n"
        "\n"
        "| Module | Purpose | Status | Note |\n"
        "|---|---|---|---|\n"
        "| ai | Describes the thing. | draft | kb/modules/ai.md |\n"
        "| services | Describes the thing. | reviewed | kb/modules/services.md |\n"
    )


def test_render_index_when_module_has_no_note_then_status_missing(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module("services", ["app/**/*.py"], {"app/a.py": "x\n"}, with_note=False)

    text = render_index(repo.root, load_config(repo.root / "milepost.toml"))

    assert "| services | (no note yet) | missing | kb/modules/services.md |" in text


def test_render_index_when_rendered_twice_then_identical(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module("services", ["app/**/*.py"], {"app/a.py": "x\n"})
    config = load_config(repo.root / "milepost.toml")

    assert render_index(repo.root, config) == render_index(repo.root, config)


def test_render_index_when_note_has_purpose_then_row_has_first_sentence_cut_to_160(
    tmp_path: Path,
) -> None:
    repo = KbRepo(tmp_path)
    long_sentence = "Handles " + "very " * 60 + "long things."
    body = "\n## Purpose\n\nFirst sentence here. Second sentence.\n\n## Gotchas\n\nx\n"
    repo.add_module("a", ["app/a/**/*.py"], {"app/a/x.py": "x\n"}, body=body)
    repo.add_module(
        "b", ["app/b/**/*.py"], {"app/b/x.py": "x\n"}, body=f"\n## Purpose\n\n{long_sentence}\n"
    )

    text = render_index(repo.root, load_config(repo.root / "milepost.toml"))

    assert "| a | First sentence here. | reviewed |" in text
    row = next(line for line in text.splitlines() if line.startswith("| b |"))
    purpose = row.split("|")[2].strip()
    assert len(purpose) == 160 and purpose.endswith("...")


def test_render_index_when_no_purpose_section_then_row_says_so(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module("a", ["app/a/**/*.py"], {"app/a/x.py": "x\n"}, body="\n## Gotchas\n\nx\n")

    text = render_index(repo.root, load_config(repo.root / "milepost.toml"))

    assert "| a | (no Purpose section) | reviewed |" in text


def test_render_index_when_purpose_contains_pipe_then_table_not_broken(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path)
    repo.add_module(
        "a", ["app/a/**/*.py"], {"app/a/x.py": "x\n"}, body="\n## Purpose\n\nReads a | b.\n"
    )

    text = render_index(repo.root, load_config(repo.root / "milepost.toml"))

    assert "| a | Reads a / b. | reviewed |" in text
