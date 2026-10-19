"""What Claude needs to write a module note: the instructions and the module's sources, after the
exclusion list, the size budget and the credential scan (SPEC section 9)."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from wcmatch import glob as wcglob

from milepost.config import Config
from milepost.core.glob import FLAGS, expand_sources
from milepost.core.hashing import compute_source_hash
from milepost.errors import UsageError

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "draft_l2.md"
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


def notice_blocks(outline_only: list[str], withheld: list[str]) -> dict[str, str]:
    """Heading -> text of what a note must say about sources the drafter did not fully read."""
    blocks = {}
    if outline_only:
        listed = ", ".join(f"`{path}`" for path in outline_only)
        blocks["Truncated draft"] = (
            "> **Truncated draft.** The sources exceeded `draft.max_source_bytes`, so these files "
            f"were summarized from their outline only and are not described here: {listed}. "
            "Raise `draft.max_source_bytes` and redraft to cover them.\n"
        )
    if withheld:
        listed = ", ".join(f"`{path}`" for path in withheld)
        blocks["Files withheld"] = (
            "> **Files withheld.** These files looked like they contain a credential, so they "
            f"were not read and are not described here: {listed}. If a person has checked they "
            "are safe, list them in `draft.secret_scan_allow` and redraft.\n"
        )
    return blocks


def source_notice(outline_only: list[str], withheld: list[str]) -> str:
    return "\n".join(notice_blocks(outline_only, withheld).values())


@dataclass
class Collected:
    text: str
    sent: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    truncated: bool = False
    contents: dict[str, str] = field(default_factory=dict)
    outline_only: list[str] = field(default_factory=list)
    withheld: list[str] = field(default_factory=list)

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
    withheld: list[str] = []
    for path in kept:
        data = (root / path).read_bytes()
        if b"\x00" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        if looks_like_secret(text) and not wcglob.globmatch(
            path, config.draft.secret_scan_allow, flags=FLAGS
        ):
            withheld.append(path)  # only this file is dropped, never the whole module
            continue
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
    return Collected(
        "".join(parts), sorted(contents), excluded, truncated, contents, outline_only, withheld
    )


def looks_like_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def scan_for_secrets(contents: dict[str, str]) -> str | None:
    """Path of the first text that looks like it holds a credential. Never returns the value."""
    for path, text in contents.items():
        if looks_like_secret(text):
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
    withheld: list[str]
    truncation_notice: str
    estimated_tokens: int


def build_draft_packet(root: Path, config: Config, module_id: str) -> DraftPacket:
    """The drafting prompt and the module's sources, after `draft.exclude`, the size budget and
    the secret scan. No model is called. A file that looks like it holds a credential is left out
    and listed in `withheld`; if that leaves nothing to read, raises UsageError."""
    module = config.modules[module_id]
    collected = collect_sources(root, config, module_id)
    if collected.withheld and not collected.contents:
        raise UsageError(
            f"module '{module_id}': every file looked like it holds a credential "
            f"({', '.join(collected.withheld)}); if a person has checked them, list them in "
            "draft.secret_scan_allow in milepost.toml"
        )
    return DraftPacket(
        module_id=module_id,
        system_prompt=_system_prompt(config, module_id),
        sources_text=collected.text,
        source_hash_now=compute_source_hash(root, module.sources, config.structure.ignore).value,
        sent_files=collected.sent,
        outline_only=collected.outline_only,
        withheld=collected.withheld,
        truncation_notice=source_notice(collected.outline_only, collected.withheld),
        estimated_tokens=collected.estimated_tokens,
    )
