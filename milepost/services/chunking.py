"""Split notes into search chunks (SPEC section 7.1)."""

import re
from dataclasses import dataclass

from milepost.core.notes import Note

MAX_CHUNK_CHARS = 2000
_HEADING = re.compile(r"^## +(.+?)\s*$")


@dataclass(frozen=True)
class Chunk:
    heading: str
    text: str


def _sections(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in body.splitlines():
        match = _HEADING.match(line)
        if match:
            sections.append((match.group(1), []))
        else:
            sections[-1][1].append(line)
    return [(heading, "\n".join(lines).strip()) for heading, lines in sections]


def _pack(paragraphs: list[str], room: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= room:
            current = candidate
            continue
        if current:
            pieces.append(current)
        current = ""
        while len(paragraph) > room:
            pieces.append(paragraph[:room])
            paragraph = paragraph[room:]
        current = paragraph
    if current:
        pieces.append(current)
    return pieces


def chunk_note(note: Note) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, content in _sections(note.body):
        if not heading and not content:
            continue
        header = f"## {heading}\n\n" if heading else ""
        text = f"## {heading}\n\n{content}".rstrip() if heading else content
        if len(text) <= MAX_CHUNK_CHARS:
            chunks.append(Chunk(heading, text))
            continue
        paragraphs = [p for p in re.split(r"\n\s*\n", content) if p.strip()]
        for piece in _pack(paragraphs, MAX_CHUNK_CHARS - len(header)):
            chunks.append(Chunk(heading, header + piece))
    return chunks


def chunk_index(text: str) -> list[Chunk]:
    """One chunk per module row of INDEX.md."""
    chunks = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 4 or cells[0] == "Module" or set(cells[0]) <= {"-"}:
            continue
        module, title, status, note = cells[:4]
        chunks.append(Chunk(module, f"Module {module}: {title}. Status: {status}. Note: {note}"))
    return chunks
