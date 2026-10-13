from milepost.core.notes import Note
from milepost.services.chunking import MAX_CHUNK_CHARS, chunk_index, chunk_note


def note(body: str) -> Note:
    return Note(meta={"id": "module/x", "level": "L2"}, body=body)


def test_chunk_note_when_split_on_headings_then_one_chunk_per_section() -> None:
    chunks = chunk_note(note("\n## Purpose\n\nDoes things.\n\n## Gotchas\n\nWatch out.\n"))

    assert [chunk.heading for chunk in chunks] == ["Purpose", "Gotchas"]
    assert "Does things." in chunks[0].text
    assert chunks[1].text.startswith("## Gotchas")


def test_chunk_note_when_text_before_first_heading_then_preamble_chunk_without_heading() -> None:
    chunks = chunk_note(note("Intro line.\n\n## Purpose\n\nDoes things.\n"))

    assert [chunk.heading for chunk in chunks] == ["", "Purpose"]
    assert chunks[0].text == "Intro line."


def test_chunk_note_when_section_over_2000_chars_then_split_on_paragraphs() -> None:
    paragraphs = [f"{label} " + "x" * 900 for label in ("alpha", "beta", "gamma")]
    chunks = chunk_note(note("## Big\n\n" + "\n\n".join(paragraphs) + "\n"))

    assert len(chunks) == 2
    assert all(len(chunk.text) <= MAX_CHUNK_CHARS for chunk in chunks)
    assert all(chunk.heading == "Big" for chunk in chunks)
    joined = "\n".join(chunk.text for chunk in chunks)
    assert all(label in joined for label in ("alpha", "beta", "gamma"))


def test_chunk_note_when_single_paragraph_over_limit_then_hard_split_within_limit() -> None:
    chunks = chunk_note(note("## Big\n\n" + "y" * 5000 + "\n"))

    assert len(chunks) >= 3
    assert all(len(chunk.text) <= MAX_CHUNK_CHARS for chunk in chunks)


def test_chunk_note_when_body_empty_then_no_chunks() -> None:
    assert chunk_note(note("\n  \n")) == []


def test_chunk_note_when_heading_has_no_body_then_heading_only_chunk_kept() -> None:
    chunks = chunk_note(note("## Empty\n\n## Next\n\ntext\n"))

    assert [chunk.heading for chunk in chunks] == ["Empty", "Next"]


def test_chunk_index_when_table_rows_then_one_chunk_per_module_row() -> None:
    text = (
        "# Codebase index\n\n| Module | Purpose | Status | Note |\n|---|---|---|---|\n"
        "| ai | Runs the tutor. | reviewed | kb/modules/ai.md |\n"
        "| services | Owns billing rules. | draft | kb/modules/services.md |\n"
    )

    chunks = chunk_index(text)

    assert [chunk.heading for chunk in chunks] == ["ai", "services"]
    assert "Owns billing rules." in chunks[1].text
