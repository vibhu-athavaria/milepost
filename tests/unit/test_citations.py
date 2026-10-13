from milepost.core.citations import cited_bullets

BODY = """
## Invariants

- Every call goes through `ai/client.py`; no route calls a provider.
- Static before dynamic: `class_topics.py::reorder` then `/topics/{id}`.
  Continued on a second line with `db_tools.py`.
- A rule with no citation at all.
- Uses `some_variable` and `Class.method()` but cites no file.

## Gotchas

* Cache key ignores the answer, see `cache.py`.

## Purpose

- `not/in/a/citing/section.py`
"""


def test_cited_bullets_when_paths_in_backticks_then_returned_with_section() -> None:
    bullets = cited_bullets(BODY)

    assert [(b.section, b.paths) for b in bullets] == [
        ("Invariants", ["ai/client.py"]),
        ("Invariants", ["class_topics.py", "db_tools.py"]),
        ("Gotchas", ["cache.py"]),
    ]


def test_cited_bullets_when_symbol_has_double_colon_then_path_part_only() -> None:
    (bullet,) = cited_bullets("## Gotchas\n\n- See `routes/auth.py::login()`.\n")

    assert bullet.paths == ["routes/auth.py"]


def test_cited_bullets_when_no_sections_then_empty() -> None:
    assert cited_bullets("## Purpose\n\nx\n") == []
