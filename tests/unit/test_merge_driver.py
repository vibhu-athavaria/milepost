from pathlib import Path

from milepost.core.notes import Note, parse_note, render_note
from milepost.services.merge_driver import merge_notes, run_merge_driver

BODY = "\n## Purpose\n\nLine one.\n\nLine two.\n\nLine three.\n"


def note(body: str = BODY, **overrides: object) -> str:
    meta: dict[str, object] = {
        "kb_schema": 1,
        "id": "module/billing",
        "level": "L2",
        "title": "Billing",
        "status": "reviewed",
        "sources": ["app/billing/**/*.py"],
        "source_hash": "sha256:base",
        "written_by": "agent",
        "written_at": "2026-10-01T00:00:00Z",
        "reviewed_by": "Jane <j@example.com>",
        "reviewed_at": "2026-10-02T00:00:00Z",
    }
    meta.update(overrides)
    return render_note(Note(meta=meta, body=body))


def test_merge_driver_when_only_ours_changed_key_then_keeps_ours() -> None:
    result = merge_notes(note(), note(title="Billing v2"), note())

    assert parse_note(result.text).meta["title"] == "Billing v2"
    assert result.body_conflict is False


def test_merge_driver_when_only_theirs_changed_key_then_takes_theirs() -> None:
    result = merge_notes(note(), note(), note(source_hash="sha256:theirs"))

    assert parse_note(result.text).meta["source_hash"] == "sha256:theirs"


def test_merge_driver_when_both_changed_source_hash_then_writes_conflict() -> None:
    result = merge_notes(note(), note(source_hash="sha256:ours"), note(source_hash="sha256:theirs"))

    assert parse_note(result.text).meta["source_hash"] == "CONFLICT"
    assert result.body_conflict is False


def test_merge_driver_when_both_changed_source_hash_to_same_value_then_keeps_it() -> None:
    result = merge_notes(note(), note(source_hash="sha256:x"), note(source_hash="sha256:x"))

    assert parse_note(result.text).meta["source_hash"] == "sha256:x"


def test_merge_driver_when_reviewed_note_only_gets_key_changes_then_stays_reviewed() -> None:
    result = merge_notes(note(), note(title="Billing v2"), note(source_hash="sha256:theirs"))
    meta = parse_note(result.text).meta

    assert meta["status"] == "reviewed"
    assert meta["reviewed_by"] == "Jane <j@example.com>"


def test_merge_driver_when_ours_reviewed_but_theirs_edited_body_then_draft() -> None:
    base = note(status="draft")
    ours = note(status="reviewed")
    theirs = note(BODY.replace("Line three.", "Line three, edited by an agent."), status="draft")

    meta = parse_note(merge_notes(base, ours, theirs).text).meta

    assert meta["status"] == "draft"
    assert "reviewed_by" not in meta


def test_merge_driver_when_both_bodies_edited_and_both_reviewed_then_draft() -> None:
    ours = note(BODY.replace("Line one.", "Line one, ours."), reviewed_at="2026-10-05T00:00:00Z")
    theirs = note(
        BODY.replace("Line three.", "Line three, theirs."), reviewed_at="2026-10-06T00:00:00Z"
    )

    result = merge_notes(note(), ours, theirs)

    assert parse_note(result.text).meta["status"] == "draft"


def test_merge_driver_when_agent_edit_on_one_side_then_draft_wins_over_reviewed() -> None:
    result = merge_notes(note(), note(), note(status="draft"))
    meta = parse_note(result.text).meta

    assert meta["status"] == "draft"
    assert "reviewed_by" not in meta
    assert "reviewed_at" not in meta


def test_merge_driver_when_bodies_edited_in_different_places_then_both_kept() -> None:
    ours = note(BODY.replace("Line one.", "Line one, ours."))
    theirs = note(BODY.replace("Line three.", "Line three, theirs."))

    result = merge_notes(note(), ours, theirs)

    assert result.body_conflict is False
    body = parse_note(result.text).body
    assert "Line one, ours." in body and "Line three, theirs." in body


def test_merge_driver_when_body_conflicts_then_leaves_markers_and_reports_conflict() -> None:
    ours = note(BODY.replace("Line two.", "Line two, ours."))
    theirs = note(BODY.replace("Line two.", "Line two, theirs."))

    result = merge_notes(note(), ours, theirs)

    assert result.body_conflict is True
    assert "<<<<<<<" in result.text and ">>>>>>>" in result.text


def test_merge_driver_when_file_has_no_frontmatter_then_plain_text_merge() -> None:
    base = "a\nb\nc\nd\ne\n"
    result = merge_notes(base, "a\nb2\nc\nd\ne\n", "a\nb\nc\nd\ne3\n")

    assert result.text == "a\nb2\nc\nd\ne3\n"
    assert result.body_conflict is False


def test_run_merge_driver_when_clean_then_writes_ours_and_returns_zero(tmp_path: Path) -> None:
    paths = {name: tmp_path / name for name in ("base", "ours", "theirs")}
    paths["base"].write_text(note())
    paths["ours"].write_text(note(title="Mine"))
    paths["theirs"].write_text(note())

    code = run_merge_driver(paths["base"], paths["ours"], paths["theirs"], "kb/modules/billing.md")

    assert code == 0
    assert parse_note(paths["ours"].read_text()).meta["title"] == "Mine"


def test_run_merge_driver_when_body_conflicts_then_returns_nonzero(tmp_path: Path) -> None:
    paths = {name: tmp_path / name for name in ("base", "ours", "theirs")}
    paths["base"].write_text(note())
    paths["ours"].write_text(note(BODY.replace("Line two.", "ours")))
    paths["theirs"].write_text(note(BODY.replace("Line two.", "theirs")))

    code = run_merge_driver(paths["base"], paths["ours"], paths["theirs"], "kb/modules/billing.md")

    assert code == 1
    assert "<<<<<<<" in paths["ours"].read_text()


def test_run_merge_driver_when_leftover_index_md_then_keeps_ours_untouched(tmp_path: Path) -> None:
    paths = {name: tmp_path / name for name in ("base", "ours", "theirs")}
    paths["base"].write_text("# Codebase index\n| a |\n")
    paths["ours"].write_text("# Codebase index\n| a | b |\n")
    paths["theirs"].write_text("# Codebase index\n| a | c |\n")

    code = run_merge_driver(paths["base"], paths["ours"], paths["theirs"], "kb/INDEX.md")

    assert code == 0
    assert paths["ours"].read_text() == "# Codebase index\n| a | b |\n"
