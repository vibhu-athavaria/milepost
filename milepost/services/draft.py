"""Draft L2 module notes with an LLM (SPEC section 9.3 and 9.5)."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wcmatch import glob as wcglob

from milepost.config import Config
from milepost.core.glob import FLAGS, expand_sources
from milepost.core.hashing import compute_source_hash
from milepost.core.notes import Note, parse_note, read_note, write_note
from milepost.errors import NoteInvalid, ProviderError, SecretDetected, UsageError
from milepost.llm.client import LlmClient, complete_with_retries

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "draft_l2.md"
PROGRESS_NAME = ".progress.json"
_OUTLINE_LINE = re.compile(
    r"^\s*(?:async\s+def|def|class|import|from|export|function|const|interface|type)\b"
)
_SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(
        r"""(?i)\b\w*(?:password|passwd|secret|token|api_?key)\w*\s*[=:]\s*['"][^'"\s]{12,}['"]"""
    ),
]


def truncation_note(outline_only: list[str]) -> str:
    listed = ", ".join(f"`{path}`" for path in outline_only)
    return (
        "> **Truncated draft.** The sources exceeded `draft.max_source_bytes`, so these files "
        f"were summarized from their outline only and are not described here: {listed}. "
        "Raise `draft.max_source_bytes` and redraft to cover them.\n"
    )


@dataclass
class Collected:
    text: str
    sent: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    truncated: bool = False
    contents: dict[str, str] = field(default_factory=dict)
    outline_only: list[str] = field(default_factory=list)

    @property
    def estimated_tokens(self) -> int:
        return len(self.text.encode("utf-8")) // 4


def _outline(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if _OUTLINE_LINE.match(line)) + "\n"


def collect_sources(root: Path, config: Config, module_id: str) -> Collected:
    module = config.modules[module_id]
    paths = expand_sources(root, module.sources, config.structure.ignore)
    excluded = [p for p in paths if wcglob.globmatch(p, config.draft.exclude, flags=FLAGS)]
    kept = [p for p in paths if p not in excluded]
    budget = config.draft.max_source_bytes
    used = 0
    parts: list[str] = []
    contents: dict[str, str] = {}
    truncated = False
    outline_only: list[str] = []
    for path in kept:
        data = (root / path).read_bytes()
        if b"\x00" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        if not truncated and used + len(data) <= budget:
            used += len(data)
            parts.append(f"=== {path} ===\n{text}\n")
            contents[path] = text
        else:
            truncated = True
            outline_only.append(path)
            outline = _outline(text)
            parts.append(f"=== {path} (outline only) ===\n{outline}")
            contents[path] = outline
    return Collected("".join(parts), sorted(contents), excluded, truncated, contents, outline_only)


def scan_for_secrets(contents: dict[str, str]) -> str | None:
    """Path of the first file that looks like it holds a credential. Never returns the value."""
    for path, text in contents.items():
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            return path
    return None


def _system_prompt(config: Config, module_id: str) -> str:
    related = config.modules[module_id].related
    lines = "\n".join(f"- `{name}`: why it matters to this module." for name in related)
    return PROMPT_PATH.read_text(encoding="utf-8").replace("{related}", lines or "None declared.")


@dataclass
class DraftPacket:
    """Everything an agent needs to write a module note itself (draft.mode = "agent")."""

    module_id: str
    system_prompt: str
    sources_text: str
    source_hash_now: str
    sent_files: list[str]
    outline_only: list[str]
    truncation_notice: str
    estimated_tokens: int


def build_draft_packet(root: Path, config: Config, module_id: str) -> DraftPacket:
    """The drafting prompt and the module's sources, after `draft.exclude`, the size budget and
    the secret scan. No model is called. Raises SecretDetected naming the file, not the value."""
    module = config.modules[module_id]
    collected = collect_sources(root, config, module_id)
    leaked = scan_for_secrets(collected.contents)
    if leaked is not None:
        raise SecretDetected(leaked)
    return DraftPacket(
        module_id=module_id,
        system_prompt=_system_prompt(config, module_id),
        sources_text=collected.text,
        source_hash_now=compute_source_hash(root, module.sources, config.structure.ignore).value,
        sent_files=collected.sent,
        outline_only=collected.outline_only,
        truncation_notice=truncation_note(collected.outline_only) if collected.truncated else "",
        estimated_tokens=collected.estimated_tokens,
    )


def _model_body(reply: str) -> str:
    try:
        body = parse_note(reply.strip() + "\n").body
    except NoteInvalid:
        body = reply
    return body.strip()


def _write_progress(kb: Path, completed: list[str]) -> None:
    (kb / PROGRESS_NAME).write_text(json.dumps({"completed": completed}, indent=2) + "\n")


def draft_modules(
    root: Path,
    config: Config,
    module_ids: list[str],
    client: LlmClient,
    model: str,
    force: bool,
    now: str,
    sleep: Callable[[float], None],
) -> list[str]:
    """Draft each module's L2 note. Returns the ids written. Progress is saved after each one."""
    kb = root / config.project.kb_dir
    for module_id in module_ids:
        if module_id not in config.modules:
            raise UsageError(f"module '{module_id}' is not declared in milepost.toml")
        note_path = kb / "modules" / f"{module_id}.md"
        if note_path.is_file() and not force and _is_reviewed(note_path):
            raise UsageError(f"module '{module_id}' has a reviewed note; use --force to redraft it")
    completed: list[str] = []
    for module_id in module_ids:
        module = config.modules[module_id]
        packet = build_draft_packet(root, config, module_id)
        try:
            reply = complete_with_retries(
                client, model, packet.system_prompt, packet.sources_text, sleep
            )
        except ProviderError as error:
            raise ProviderError(f"module '{module_id}': {error}") from error
        body = _model_body(reply)
        if not body:
            raise ProviderError(f"module '{module_id}': the model returned an empty note")
        if packet.truncation_notice:
            body = packet.truncation_notice + "\n" + body
        note = Note(
            meta={
                "kb_schema": 1,
                "id": f"module/{module_id}",
                "level": "L2",
                "title": module.title,
                "status": "draft",
                "sources": module.sources,
                "source_hash": packet.source_hash_now,
                "related": module.related,
                "written_by": "draft-command",
                "written_at": now,
            },
            body="\n" + body + "\n",
        )
        write_note(note, kb / "modules" / f"{module_id}.md")
        completed.append(module_id)
        _write_progress(kb, completed)
    return completed


def _is_reviewed(path: Path) -> bool:
    try:
        return read_note(path).meta.get("status") == "reviewed"
    except NoteInvalid:
        return False
