from milepost.core.notes import purpose_line, section


def test_section_when_heading_present_then_text_up_to_next_heading() -> None:
    body = "\n## Purpose\n\nOne.\n\n## Gotchas\n\nTwo.\n"

    assert section(body, "Purpose") == "\n\nOne.\n\n"
    assert section(body, "Gotchas") == "\n\nTwo.\n"


def test_section_when_heading_absent_then_none() -> None:
    assert section("\n## Purpose\n\nOne.\n", "Gotchas") is None


def test_section_when_heading_case_differs_then_still_found() -> None:
    assert section("## purpose\nx\n", "Purpose") == "\nx\n"


def test_purpose_line_when_multiline_sentences_then_first_sentence_flattened() -> None:
    body = "## Purpose\n\nThe HTTP layer:\nFastAPI routers. Business logic is elsewhere.\n"

    assert purpose_line(body) == "The HTTP layer: FastAPI routers."


def test_purpose_line_when_no_terminal_punctuation_then_whole_text() -> None:
    assert purpose_line("## Purpose\n\nJust words\n") == "Just words"


def test_purpose_line_when_empty_section_then_none() -> None:
    assert purpose_line("## Purpose\n\n## Gotchas\n\nx\n") is None
