"""Builds throwaway git repositories with a milepost.toml, sources, and correct notes."""

import subprocess
from pathlib import Path

from milepost.config import Structure
from milepost.core.hashing import compute_source_hash
from milepost.core.notes import Note, read_note, write_note

GIT = [
    "git",
    "-c",
    "user.name=test",
    "-c",
    "user.email=test@example.com",
    "-c",
    "commit.gpgsign=false",
]


class KbRepo:
    def __init__(self, root: Path, extra_config: str = "") -> None:
        self.root = root
        self.extra_config = extra_config
        self.modules: dict[str, list[str]] = {}
        root.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        done = subprocess.run(
            [*GIT, *args], cwd=self.root, check=True, capture_output=True, text=True
        )
        return done.stdout

    def write(self, rel: str, text: str = "") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)

    def checkout(self, branch: str, create: bool = False) -> None:
        self.git("checkout", "-q", *(["-b"] if create else []), branch)

    def write_config(self) -> None:
        lines = ["[project]", 'name = "example"', ""]
        for module_id, sources in self.modules.items():
            quoted = ", ".join(f'"{source}"' for source in sources)
            lines += [f"[modules.{module_id}]", f"sources = [{quoted}]", ""]
        self.write("milepost.toml", "\n".join(lines) + "\n" + self.extra_config)

    def hash_of(self, sources: list[str]) -> str:
        return compute_source_hash(self.root, sources, Structure().ignore).value

    def write_note_file(
        self,
        rel: str,
        note_id: str,
        level: str,
        sources: list[str],
        status: str = "reviewed",
        body: str = "\n## Purpose\n\nDescribes the thing.\n",
    ) -> None:
        note = Note(
            meta={
                "kb_schema": 1,
                "id": note_id,
                "level": level,
                "title": note_id,
                "status": status,
                "sources": sources,
                "source_hash": self.hash_of(sources),
                "written_by": "agent",
                "written_at": "2026-10-07T09:12:00Z",
            },
            body=body,
        )
        write_note(note, self.root / rel)

    def add_module(
        self,
        module_id: str,
        sources: list[str],
        files: dict[str, str],
        with_note: bool = True,
        status: str = "reviewed",
        body: str = "\n## Purpose\n\nDescribes the thing.\n",
    ) -> None:
        for rel, text in files.items():
            self.write(rel, text)
        self.modules[module_id] = sources
        self.write_config()
        if with_note:
            self.write_note_file(
                f"kb/modules/{module_id}.md", f"module/{module_id}", "L2", sources, status, body
            )

    def add_file_note(self, path: str) -> None:
        self.write_note_file(f"kb/files/{path}.md", f"file/{path}", "L3", [path])

    def set_hash(self, rel: str, value: str) -> None:
        note = read_note(self.root / rel)
        note.meta["source_hash"] = value
        write_note(note, self.root / rel)
