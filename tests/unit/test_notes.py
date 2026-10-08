from pathlib import Path

import pytest

from kbmap.core.notes import Note, parse_note, read_note, render_note, validate_note, write_note
from kbmap.errors import NoteInvalid

VALID = """\
---
kb_schema: 1
id: module/services
level: L2
title: Services
status: draft
sources:
  - backend/app/services/**/*.py
source_hash: sha256:9f2c
related: [ai, data]
written_by: agent
written_at: 2026-10-07T09:12:00Z
---

## Purpose

Does the work.
"""


def codes(note: Note, rel_path: str = "modules/services.md") -> list[str]:
    return [finding.code for finding in validate_note(note, rel_path)]


def test_parse_note_when_valid_frontmatter_then_returns_note() -> None:
    note = parse_note(VALID)

    assert note.meta["id"] == "module/services"
    assert note.meta["related"] == ["ai", "data"]
    assert note.meta["written_at"] == "2026-10-07T09:12:00Z"
    assert "## Purpose" in note.body


def test_parse_note_when_no_frontmatter_then_raises_note_invalid() -> None:
    with pytest.raises(NoteInvalid):
        parse_note("## Purpose\n\nNo frontmatter here.\n")


def test_parse_note_when_yaml_malformed_then_raises_note_invalid() -> None:
    with pytest.raises(NoteInvalid):
        parse_note("---\nkb_schema: [1\n---\nbody\n")


def test_parse_note_when_frontmatter_not_a_mapping_then_raises_note_invalid() -> None:
    with pytest.raises(NoteInvalid):
        parse_note("---\n- a\n- b\n---\nbody\n")


def test_validate_note_when_note_is_valid_then_no_findings() -> None:
    assert codes(parse_note(VALID)) == []


def test_validate_note_when_required_key_missing_then_reports_error() -> None:
    note = parse_note(VALID.replace("title: Services\n", ""))

    assert "MISSING_KEY" in codes(note)


def test_validate_note_when_l1_or_l4_has_no_sources_then_no_error() -> None:
    text = (
        "---\nkb_schema: 1\nid: passage/slug\nlevel: L4\ntitle: T\nstatus: draft\n"
        "written_by: agent\nwritten_at: 2026-10-07T09:12:00Z\n---\nbody\n"
    )

    assert codes(parse_note(text), "passages/slug.md") == []


def test_validate_note_when_kb_schema_not_one_then_reports_error() -> None:
    note = parse_note(VALID.replace("kb_schema: 1", "kb_schema: 2"))

    assert "SCHEMA_VERSION" in codes(note)


def test_validate_note_when_status_unknown_then_reports_error() -> None:
    note = parse_note(VALID.replace("status: draft", "status: final"))

    assert "INVALID_STATUS" in codes(note)


def test_validate_note_when_id_mismatches_path_then_reports_error() -> None:
    note = parse_note(VALID)

    assert "ID_PATH_MISMATCH" in codes(note, "modules/other.md")


def test_validate_note_when_file_note_then_id_derived_from_nested_path() -> None:
    text = VALID.replace("module/services", "file/app/x.py").replace("L2", "L3")

    assert codes(parse_note(text), "files/app/x.py.md") == []


def test_validate_note_when_source_hash_conflict_then_reports_conflict_code() -> None:
    note = parse_note(VALID.replace("sha256:9f2c", "CONFLICT"))

    findings = validate_note(note, "modules/services.md")

    conflict = [f for f in findings if f.code == "SOURCE_HASH_CONFLICT"]
    assert len(conflict) == 1
    assert "kbmap rehash module/services" in conflict[0].message


def test_validate_note_when_body_empty_then_reports_error() -> None:
    note = parse_note(VALID.split("---\n\n")[0] + "---\n")

    assert "EMPTY_BODY" in codes(note)


def test_write_note_when_round_trip_then_frontmatter_and_body_unchanged(tmp_path: Path) -> None:
    note = parse_note(VALID)
    path = tmp_path / "note.md"

    write_note(note, path)
    again = read_note(path)

    assert again.meta == note.meta
    assert again.body == note.body


def test_write_note_when_written_twice_then_files_are_byte_identical(tmp_path: Path) -> None:
    note = parse_note(VALID)
    first, second = tmp_path / "a.md", tmp_path / "b.md"

    write_note(note, first)
    write_note(read_note(first), second)

    assert first.read_bytes() == second.read_bytes()


def test_write_note_when_keys_written_then_order_is_stable() -> None:
    shuffled = Note(
        meta={
            "written_at": "2026-10-07T09:12:00Z",
            "zzz_extra": 1,
            "title": "Services",
            "id": "module/services",
            "kb_schema": 1,
            "level": "L2",
            "status": "draft",
            "written_by": "agent",
            "aaa_extra": 2,
        },
        body="\nbody\n",
    )

    keys = [line.split(":")[0] for line in render_note(shuffled).splitlines()[1:10]]

    assert keys == [
        "kb_schema",
        "id",
        "level",
        "title",
        "status",
        "written_by",
        "written_at",
        "aaa_extra",
        "zzz_extra",
    ]
