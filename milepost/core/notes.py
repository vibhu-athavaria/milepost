"""Note files: markdown with YAML frontmatter (SPEC section 4)."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from milepost.core.findings import Finding
from milepost.errors import NoteInvalid

KEY_ORDER = [
    "kb_schema",
    "id",
    "level",
    "title",
    "status",
    "sources",
    "source_hash",
    "related",
    "written_by",
    "written_at",
    "reviewed_by",
    "reviewed_at",
]
BASE_KEYS = ["kb_schema", "id", "level", "title", "status", "written_by", "written_at"]
HASHED_KEYS = ["sources", "source_hash"]
LEVELS = {"L1", "L2", "L3", "L4"}
HASHED_LEVELS = {"L2", "L3"}
STATUSES = {"draft", "reviewed"}
ID_PREFIX_BY_DIR = {"modules": "module", "files": "file", "passages": "passage"}

_FRONTMATTER = re.compile(r"---\n(.*?)^---[ \t]*(?:\n|\Z)", re.DOTALL | re.MULTILINE)


class _Loader(yaml.SafeLoader):
    """SafeLoader that keeps ISO timestamps as strings, so written_at round-trips."""


_Loader.yaml_implicit_resolvers = {
    first_char: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first_char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@dataclass
class Note:
    meta: dict[str, Any]
    body: str


def parse_note(text: str) -> Note:
    match = _FRONTMATTER.match(text)
    if match is None:
        raise NoteInvalid("note has no frontmatter block")
    try:
        meta = yaml.load(match.group(1), Loader=_Loader)  # noqa: S506 - _Loader is a SafeLoader
    except yaml.YAMLError as error:
        raise NoteInvalid(f"frontmatter is not valid YAML: {error}") from error
    if not isinstance(meta, dict):
        raise NoteInvalid("frontmatter must be a YAML mapping")
    return Note(meta=meta, body=text[match.end() :])


def read_note(path: Path) -> Note:
    return parse_note(path.read_text(encoding="utf-8"))


def render_note(note: Note) -> str:
    ordered = {key: note.meta[key] for key in KEY_ORDER if key in note.meta}
    extras = sorted(key for key in note.meta if key not in KEY_ORDER)
    ordered.update({key: note.meta[key] for key in extras})
    frontmatter = yaml.safe_dump(
        ordered, sort_keys=False, default_flow_style=False, allow_unicode=True, width=10_000
    )
    return f"---\n{frontmatter}---\n{note.body}"


def write_note(note: Note, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_note(note).encode("utf-8"))


def note_path_for_id(kb_dir: Path, note_id: str) -> Path | None:
    """File that holds note `note_id`, or None if the id has no known prefix."""
    prefix, _, name = note_id.partition("/")
    for directory, id_prefix in ID_PREFIX_BY_DIR.items():
        if id_prefix == prefix and name:
            return kb_dir / directory / f"{name}.md"
    return None


def expected_id(rel_path: str) -> str | None:
    """Note id implied by a path relative to the kb directory, or None if not a note location."""
    parts = Path(rel_path).parts
    if len(parts) < 2 or parts[0] not in ID_PREFIX_BY_DIR:
        return None
    name = "/".join(parts[1:])
    return f"{ID_PREFIX_BY_DIR[parts[0]]}/{name.removesuffix('.md')}"


def validate_note(note: Note, rel_path: str) -> list[Finding]:
    def failure(code: str, message: str) -> Finding:
        return Finding("failure", code, rel_path, message)

    meta = note.meta
    findings: list[Finding] = []
    required = list(BASE_KEYS)
    if meta.get("level") in HASHED_LEVELS:
        required += HASHED_KEYS
    for key in required:
        if key not in meta:
            findings.append(failure("MISSING_KEY", f"required key '{key}' is missing"))

    if "kb_schema" in meta and meta["kb_schema"] != 1:
        findings.append(failure("SCHEMA_VERSION", f"kb_schema must be 1, got {meta['kb_schema']}"))
    if "level" in meta and meta["level"] not in LEVELS:
        findings.append(
            failure("INVALID_LEVEL", f"level must be one of L1-L4, got {meta['level']}")
        )
    if "status" in meta and meta["status"] not in STATUSES:
        findings.append(
            failure("INVALID_STATUS", f"status must be draft or reviewed, got {meta['status']}")
        )

    if "id" in meta and meta["id"] != expected_id(rel_path):
        findings.append(
            failure("ID_PATH_MISMATCH", f"id '{meta['id']}' does not match path '{rel_path}'")
        )
    if meta.get("source_hash") == "CONFLICT":
        findings.append(
            failure(
                "SOURCE_HASH_CONFLICT",
                f"source_hash is CONFLICT; run `milepost rehash {meta.get('id', '<note-id>')}` "
                "after reviewing the prose",
            )
        )
    if not note.body.strip():
        findings.append(failure("EMPTY_BODY", "note body is empty"))
    return findings
