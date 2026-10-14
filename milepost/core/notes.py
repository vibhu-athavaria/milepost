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
    "title",
    "status",
    "sources",
    "related",
    "written_by",
    "written_at",
    "reviewed_by",
    "reviewed_at",
]
BASE_KEYS = ["kb_schema", "id", "title", "status", "sources", "written_by", "written_at"]
STATUSES = {"draft", "reviewed"}
ID_PREFIX_BY_DIR = {"modules": "module"}
# Keys older versions wrote. They are tolerated when reading and dropped when writing.
LEGACY_KEYS = {"level", "source_hash"}

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
    extras = sorted(key for key in note.meta if key not in KEY_ORDER and key not in LEGACY_KEYS)
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
    for key in BASE_KEYS:
        if key not in meta:
            findings.append(failure("MISSING_KEY", f"required key '{key}' is missing"))

    if "kb_schema" in meta and meta["kb_schema"] != 1:
        findings.append(failure("SCHEMA_VERSION", f"kb_schema must be 1, got {meta['kb_schema']}"))
    if "status" in meta and meta["status"] not in STATUSES:
        findings.append(
            failure("INVALID_STATUS", f"status must be draft or reviewed, got {meta['status']}")
        )

    if "id" in meta and meta["id"] != expected_id(rel_path):
        findings.append(
            failure("ID_PATH_MISMATCH", f"id '{meta['id']}' does not match path '{rel_path}'")
        )
    if not note.body.strip():
        findings.append(failure("EMPTY_BODY", "note body is empty"))
    return findings


_HEADING = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)
PURPOSE_MAX = 160


def section(body: str, heading: str) -> str | None:
    """Text of the `## heading` section (up to the next `##` heading), or None if absent."""
    matches = list(_HEADING.finditer(body))
    for index, match in enumerate(matches):
        if match.group(1).strip().lower() == heading.lower():
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            return body[match.end() : end]
    return None


def purpose_line(body: str) -> str | None:
    """First sentence of the Purpose section, whitespace collapsed, cut to PURPOSE_MAX."""
    text = section(body, "Purpose")
    if text is None:
        return None
    flat = " ".join(text.split()).replace("|", "/")
    if not flat:
        return None
    sentence = re.match(r".+?[.!?](?=\s|$)", flat)
    result = sentence.group(0) if sentence else flat
    return result if len(result) <= PURPOSE_MAX else result[: PURPOSE_MAX - 3].rstrip() + "..."
