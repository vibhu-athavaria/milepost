import csv
import io
import json
import os
from pathlib import Path
from typing import Any

from pilot_usage import (
    RunUsage,
    find_logs,
    main,
    parse_log,
    project_dirs,
    render_csv,
    render_json,
    render_table,
)


def assistant(
    msg_id: str,
    ts: str,
    usage: dict[str, int],
    tools: list[str] | None = None,
    model: str = "claude-sonnet-5-5",
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "uuid": f"u-{msg_id}-{ts}",
        "timestamp": ts,
        "message": {
            "id": msg_id,
            "model": model,
            "usage": usage,
            "content": [{"type": "tool_use", "name": name} for name in tools or []],
        },
    }


def usage(inp: int = 0, out: int = 0, create: int = 0, read: int = 0) -> dict[str, int]:
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_creation_input_tokens": create,
        "cache_read_input_tokens": read,
    }


def write_log(
    path: Path, entries: list[dict[str, Any]], raw_lines: list[str] | None = None
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(entry) for entry in entries] + (raw_lines or [])
    path.write_text("\n".join(lines) + "\n")
    return path


def test_parse_log_when_message_logged_repeatedly_then_counted_once_with_max_fields(
    tmp_path: Path,
) -> None:
    log = write_log(
        tmp_path / "agent-a.jsonl",
        [
            assistant("m1", "2026-10-09T01:00:00Z", usage(inp=3, out=10, create=1000, read=0)),
            assistant("m1", "2026-10-09T01:00:01Z", usage(inp=3, out=250, create=1000, read=0)),
            assistant("m1", "2026-10-09T01:00:02Z", usage(inp=3, out=400, create=1000, read=0)),
        ],
    )

    run = parse_log(log)

    assert run.turns == 1
    assert run.fresh_input == 1003
    assert run.output_tokens_logged == 400


def test_parse_log_when_several_messages_then_fresh_input_and_cache_read_summed(
    tmp_path: Path,
) -> None:
    log = write_log(
        tmp_path / "agent-a.jsonl",
        [
            assistant("m1", "2026-10-09T01:00:00Z", usage(inp=5, create=1000, read=0)),
            assistant("m2", "2026-10-09T01:00:05Z", usage(inp=2, create=200, read=1005)),
        ],
    )

    run = parse_log(log)

    assert run.fresh_input == 1207
    assert run.cache_read == 1005


def test_parse_log_when_first_turn_has_context_then_fresh_after_first_turn_excludes_it(
    tmp_path: Path,
) -> None:
    log = write_log(
        tmp_path / "agent-a.jsonl",
        [
            assistant("m1", "2026-10-09T01:00:00Z", usage(inp=5, create=58000, read=0)),
            assistant("m2", "2026-10-09T01:00:05Z", usage(inp=2, create=3000, read=58005)),
        ],
    )

    run = parse_log(log)

    assert run.first_turn_context == 58005
    assert run.fresh_after_first_turn == 3002


def test_parse_log_when_cache_warm_on_first_turn_then_fresh_after_first_turn_not_negative(
    tmp_path: Path,
) -> None:
    log = write_log(
        tmp_path / "agent-a.jsonl",
        [assistant("m1", "2026-10-09T01:00:00Z", usage(inp=5, create=10, read=58000))],
    )

    run = parse_log(log)

    assert run.fresh_after_first_turn == 0
    assert run.first_turn_context == 58015


def test_parse_log_when_tools_used_then_counts_exclude_handback(tmp_path: Path) -> None:
    log = write_log(
        tmp_path / "agent-a.jsonl",
        [
            assistant("m1", "2026-10-09T01:00:00Z", usage(), ["Bash", "Read"]),
            assistant("m2", "2026-10-09T01:00:05Z", usage(), ["Bash", "SubagentHandback"]),
        ],
    )

    run = parse_log(log)

    assert run.tool_calls == 3
    assert run.tools == {"Bash": 2, "Read": 1}


def test_parse_log_when_long_idle_gap_then_active_time_excludes_it_but_wall_includes_it(
    tmp_path: Path,
) -> None:
    log = write_log(
        tmp_path / "agent-a.jsonl",
        [
            assistant("m1", "2026-10-09T01:00:00Z", usage()),
            assistant("m2", "2026-10-09T01:01:00Z", usage()),
            assistant("m3", "2026-10-09T01:31:00Z", usage()),
            assistant("m4", "2026-10-09T01:31:30Z", usage()),
        ],
    )

    run = parse_log(log)

    assert run.active_seconds == 90
    assert run.wall_seconds == 31 * 60 + 30


def test_parse_log_when_meta_json_present_then_label_is_description(tmp_path: Path) -> None:
    log = write_log(tmp_path / "agent-a.jsonl", [assistant("m1", "2026-10-09T01:00:00Z", usage())])
    (tmp_path / "agent-a.meta.json").write_text(json.dumps({"description": "T9 harness"}))

    assert parse_log(log).label == "T9 harness"


def test_parse_log_when_session_log_has_title_then_label_is_last_ai_title(tmp_path: Path) -> None:
    log = write_log(
        tmp_path / "abc.jsonl",
        [
            {"type": "ai-title", "aiTitle": "First title"},
            assistant("m1", "2026-10-09T01:00:00Z", usage()),
            {"type": "ai-title", "aiTitle": "Final title"},
        ],
    )

    assert parse_log(log).label == "Final title"


def test_parse_log_when_no_label_source_then_label_is_file_stem(tmp_path: Path) -> None:
    log = write_log(
        tmp_path / "agent-zzz.jsonl", [assistant("m1", "2026-10-09T01:00:00Z", usage())]
    )

    assert parse_log(log).label == "agent-zzz"


def test_parse_log_when_lines_malformed_or_synthetic_model_then_skipped(tmp_path: Path) -> None:
    log = write_log(
        tmp_path / "agent-a.jsonl",
        [
            assistant("m1", "2026-10-09T01:00:00Z", usage(inp=1)),
            assistant("m2", "2026-10-09T01:00:01Z", usage(inp=1), model="<synthetic>"),
        ],
        raw_lines=["not json {", ""],
    )

    run = parse_log(log)

    assert run.models == ["claude-sonnet-5-5"]
    assert run.turns == 2


def test_project_dirs_when_worktree_and_sibling_projects_exist_then_only_exact_and_worktrees(
    tmp_path: Path,
) -> None:
    root = tmp_path / "projects"
    for name in [
        "-Users-me-Projects-kaihle",
        "-Users-me-Projects-kaihle--claude-worktrees-feature-x",
        "-Users-me-Projects-kaihle-www",
        "-Users-me-Projects-other",
    ]:
        (root / name).mkdir(parents=True)

    found = sorted(path.name for path in project_dirs(Path("/Users/me/Projects/kaihle"), root))

    assert found == [
        "-Users-me-Projects-kaihle",
        "-Users-me-Projects-kaihle--claude-worktrees-feature-x",
    ]


def test_find_logs_when_subagents_requested_then_newest_n_returned(tmp_path: Path) -> None:
    project = tmp_path / "-Users-me-Projects-kaihle"
    logs = []
    for index in range(4):
        path = write_log(project / "sess1" / "subagents" / f"agent-{index}.jsonl", [])
        os.utime(path, (1_000 + index, 1_000 + index))
        logs.append(path)
    write_log(project / "sess1.jsonl", [])  # a main session log must not be picked up

    found = find_logs([project], last=2, kind="subagents")

    assert sorted(path.name for path in found) == ["agent-2.jsonl", "agent-3.jsonl"]


def test_find_logs_when_sessions_requested_then_main_logs_only(tmp_path: Path) -> None:
    project = tmp_path / "-Users-me-Projects-kaihle"
    write_log(project / "sess1" / "subagents" / "agent-1.jsonl", [])
    main_log = write_log(project / "sess1.jsonl", [])

    assert find_logs([project], last=5, kind="sessions") == [main_log]


def sample_runs(tmp_path: Path) -> list[RunUsage]:
    log = write_log(
        tmp_path / "agent-a.jsonl",
        [
            assistant("m1", "2026-10-09T01:00:00Z", usage(inp=5, out=7, create=58000)),
            assistant(
                "m2", "2026-10-09T01:00:30Z", usage(inp=2, out=9, create=3000, read=58005), ["Bash"]
            ),
        ],
    )
    (tmp_path / "agent-a.meta.json").write_text(json.dumps({"description": "Task A"}))
    return [parse_log(log)]


def test_render_table_when_runs_given_then_has_headline_columns_and_no_output_column(
    tmp_path: Path,
) -> None:
    text = render_table(sample_runs(tmp_path))

    assert "Task A" in text
    assert "fresh_after_first" in text
    assert "output" not in text.split("\n")[0]
    assert "undercount" in text


def test_render_csv_when_runs_given_then_rows_parse_and_include_logged_output(
    tmp_path: Path,
) -> None:
    rows = list(csv.DictReader(io.StringIO(render_csv(sample_runs(tmp_path)))))

    assert rows[0]["label"] == "Task A"
    assert rows[0]["fresh_after_first_turn"] == "3002"
    assert rows[0]["output_tokens_logged"] == "16"
    assert rows[0]["tool_calls"] == "1"


def test_render_json_when_runs_given_then_parses_with_tool_breakdown(tmp_path: Path) -> None:
    data = json.loads(render_json(sample_runs(tmp_path)))

    assert data[0]["label"] == "Task A"
    assert data[0]["tools"] == {"Bash": 1}


def test_main_when_no_logs_found_then_exit_two_with_message(tmp_path: Path, capsys: Any) -> None:
    code = main(["--project", "/Users/me/Projects/none", "--projects-root", str(tmp_path)])

    assert code == 2
    assert "no sub-agent logs" in capsys.readouterr().err


def test_main_when_explicit_files_given_then_prints_table(tmp_path: Path, capsys: Any) -> None:
    log = sample_runs(tmp_path)[0].path

    code = main([str(log)])

    assert code == 0
    assert "Task A" in capsys.readouterr().out
