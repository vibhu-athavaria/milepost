"""Summarize token usage and tool calls from Claude Code logs, for the milepost pilot (TASKS M5a).

Each sub-agent log (or main session log) is one "run". Examples:

    python scripts/pilot_usage.py --project /Users/me/Projects/myrepo --last 5
    python scripts/pilot_usage.py --project ~/Projects/myrepo --kind sessions --format csv
    python scripts/pilot_usage.py path/to/agent-abc.jsonl path/to/agent-def.jsonl

Reliability notes, from inspecting real logs:
- One response is written to the log several times (streaming), so usage is deduplicated by
  message id, taking the largest value of each field.
- The first turn carries a fixed context (system prompt, tools, CLAUDE.md), about 58k tokens.
  `fresh_after_first_turn` excludes it, which is the number to compare between runs.
- `output_tokens_logged` looks undercounted, so the table omits it; csv and json include it.
- Wall time includes idle waits; `active` counts only gaps of two minutes or less.
- Reading files through Bash cannot be counted reliably, so tool-call count is used instead.
"""

import argparse
import csv
import io
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

IDLE_GAP_SECONDS = 120
IGNORED_TOOLS = {"SubagentHandback"}
IGNORED_MODELS = {"<synthetic>"}
USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
WORKTREE_INFIX = "--claude-worktrees-"
DEFAULT_PROJECTS_ROOT = Path.home() / ".claude" / "projects"

Kind = Literal["subagents", "sessions"]


@dataclass
class RunUsage:
    path: Path
    label: str
    started: str
    models: list[str]
    turns: int
    first_turn_context: int
    fresh_input: int
    fresh_after_first_turn: int
    cache_read: int
    output_tokens_logged: int
    tool_calls: int
    tools: dict[str, int]
    active_seconds: int
    wall_seconds: int


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _fresh(usage: dict[str, int]) -> int:
    return usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)


def parse_log(path: Path) -> RunUsage:
    usage_by_message: dict[str, dict[str, int]] = {}
    order: list[str] = []
    models: set[str] = set()
    tool_keys: dict[str, str] = {}
    stamps: list[datetime] = []
    title = ""

    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("timestamp"), str):
            stamps.append(_timestamp(entry["timestamp"]))
        if entry.get("type") == "ai-title" and entry.get("aiTitle"):
            title = str(entry["aiTitle"])
        message = entry.get("message")
        if entry.get("type") != "assistant" or not isinstance(message, dict):
            continue
        message_id = str(message.get("id") or entry.get("uuid"))
        if message_id not in usage_by_message:
            usage_by_message[message_id] = {}
            order.append(message_id)
        merged = usage_by_message[message_id]
        for key in USAGE_KEYS:
            value = (message.get("usage") or {}).get(key) or 0
            merged[key] = max(merged.get(key, 0), int(value))
        if message.get("model") and message["model"] not in IGNORED_MODELS:
            models.add(str(message["model"]))
        for index, block in enumerate(message.get("content") or []):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = str(block.get("name"))
                key = str(block.get("id") or f"{message_id}:{index}:{name}")
                tool_keys[key] = name

    tools: dict[str, int] = {}
    for name in tool_keys.values():
        if name not in IGNORED_TOOLS:
            tools[name] = tools.get(name, 0) + 1

    totals = {key: sum(u.get(key, 0) for u in usage_by_message.values()) for key in USAGE_KEYS}
    first = usage_by_message[order[0]] if order else {}
    fresh_input = totals["input_tokens"] + totals["cache_creation_input_tokens"]
    stamps.sort()
    gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:], strict=False)]

    return RunUsage(
        path=path,
        label=_label(path, title),
        started=stamps[0].isoformat() if stamps else "",
        models=sorted(models),
        turns=len(order),
        first_turn_context=_fresh(first) + first.get("cache_read_input_tokens", 0),
        fresh_input=fresh_input,
        fresh_after_first_turn=max(fresh_input - _fresh(first), 0),
        cache_read=totals["cache_read_input_tokens"],
        output_tokens_logged=totals["output_tokens"],
        tool_calls=sum(tools.values()),
        tools=dict(sorted(tools.items())),
        active_seconds=int(sum(gap for gap in gaps if gap <= IDLE_GAP_SECONDS)),
        wall_seconds=int((stamps[-1] - stamps[0]).total_seconds()) if stamps else 0,
    )


def _label(path: Path, title: str) -> str:
    meta = path.with_name(f"{path.stem}.meta.json")
    if meta.is_file():
        try:
            description = json.loads(meta.read_text(encoding="utf-8")).get("description")
        except json.JSONDecodeError:
            description = None
        if description:
            return str(description)
    return title or path.stem


def project_dirs(repo: Path, projects_root: Path) -> list[Path]:
    """Claude Code's log folders for a repo: the repo itself and its worktrees, nothing else."""
    name = re.sub(r"[^A-Za-z0-9]", "-", str(repo))
    if not projects_root.is_dir():
        return []
    return sorted(
        d
        for d in projects_root.iterdir()
        if d.is_dir() and (d.name == name or d.name.startswith(name + WORKTREE_INFIX))
    )


def find_logs(dirs: Sequence[Path], last: int, kind: Kind) -> list[Path]:
    pattern = "*/subagents/agent-*.jsonl" if kind == "subagents" else "*.jsonl"
    found = [path for d in dirs for path in d.glob(pattern)]
    found.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return found[:last]


def _clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def render_table(runs: Sequence[RunUsage]) -> str:
    header = ["task", "floor", "fresh_after_first", "fresh_total", "cache_read", "turns", "tools"]
    header += ["active", "wall"]
    rows = [
        [
            run.label[:40],
            f"{run.first_turn_context:,}",
            f"{run.fresh_after_first_turn:,}",
            f"{run.fresh_input:,}",
            f"{run.cache_read:,}",
            str(run.turns),
            str(run.tool_calls),
            _clock(run.active_seconds),
            _clock(run.wall_seconds),
        ]
        for run in runs
    ]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]

    def fmt(row: list[str]) -> str:
        cells = [row[0].ljust(widths[0])] + [
            cell.rjust(w) for cell, w in zip(row[1:], widths[1:], strict=True)
        ]
        return "  ".join(cells)

    lines = [fmt(header), *(fmt(row) for row in rows)]
    lines += [
        "",
        "floor = fixed context on the first turn; compare fresh_after_first between runs.",
        "active = gaps of 2 minutes or less; wall includes idle waits.",
        "Output tokens are omitted: logged values look undercounted (see --format csv or json).",
    ]
    return "\n".join(lines)


CSV_FIELDS = [
    "label",
    "path",
    "started",
    "models",
    "turns",
    "first_turn_context",
    "fresh_input",
    "fresh_after_first_turn",
    "cache_read",
    "output_tokens_logged",
    "tool_calls",
    "active_seconds",
    "wall_seconds",
]


def _record(run: RunUsage) -> dict[str, Any]:
    record = asdict(run)
    record["path"] = str(run.path)
    return record


def render_csv(runs: Sequence[RunUsage]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    for run in runs:
        record = _record(run)
        record["models"] = ";".join(run.models)
        writer.writerow(record)
    return buffer.getvalue()


def render_json(runs: Sequence[RunUsage]) -> str:
    return json.dumps([_record(run) for run in runs], indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize Claude Code usage for the milepost pilot."
    )
    parser.add_argument("files", nargs="*", type=Path, help="log files to summarize")
    parser.add_argument(
        "--project", type=Path, help="repo path whose logs to read, e.g. ~/Projects/myrepo"
    )
    parser.add_argument("--projects-root", type=Path, default=DEFAULT_PROJECTS_ROOT)
    parser.add_argument("--last", type=int, default=5, help="how many newest logs (default 5)")
    parser.add_argument("--kind", choices=["subagents", "sessions"], default="subagents")
    parser.add_argument("--format", choices=["table", "csv", "json"], default="table")
    args = parser.parse_args(argv)

    logs: list[Path] = list(args.files)
    if not logs:
        if args.project is None:
            print("error: give log files or --project <repo path>", file=sys.stderr)
            return 2
        repo = args.project.expanduser().absolute()
        logs = find_logs(project_dirs(repo, args.projects_root), args.last, args.kind)
        if not logs:
            noun = "sub-agent" if args.kind == "subagents" else "session"
            print(
                f"error: no {noun} logs found for {repo} under {args.projects_root}",
                file=sys.stderr,
            )
            return 2

    runs = sorted((parse_log(path) for path in logs), key=lambda run: run.started)
    render = {"table": render_table, "csv": render_csv, "json": render_json}[args.format]
    print(render(runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
