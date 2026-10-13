"""Starts `milepost serve` as a subprocess and talks to it over stdio like a real client."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from support.kb_repo import KbRepo

EXPECTED_TOOLS = {
    "kb_overview",
    "kb_module",
    "kb_file",
    "kb_search",
    "kb_update",
    "kb_check",
    "kb_draft_module",
    "kb_outline",
    "kb_impact",
    "kb_sync",
}


def make_repo(tmp_path: Path) -> KbRepo:
    repo = KbRepo(tmp_path / "repo")
    repo.add_module(
        "billing",
        ["app/billing/**/*.py"],
        {"app/billing/charge.py": "def charge(card):\n    return card\n"},
    )
    repo.git("config", "user.name", "t")
    repo.git("config", "user.email", "t@example.com")
    repo.commit("base")
    return repo


async def session_calls(root: Path, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "milepost", "serve", "--repo", str(root)]
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
        results: list[Any] = [{tool.name for tool in listed.tools}]
        for name, arguments in calls:
            results.append(await session.call_tool(name, arguments))
        return results


def payload(result: Any) -> dict[str, Any]:
    if result.structured_content:
        return dict(result.structured_content)
    return dict(json.loads(result.content[0].text))


def test_mcp_stdio_when_client_lists_tools_then_ten_tools_returned(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    (names,) = asyncio.run(session_calls(repo.root, []))

    assert names == EXPECTED_TOOLS


def test_mcp_stdio_when_each_tool_called_then_responses_carry_next_steps(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    read_hash = repo.hash_of(["app/billing/**/*.py"])
    calls: list[tuple[str, dict[str, Any]]] = [
        ("kb_overview", {}),
        ("kb_module", {"id": "billing"}),
        ("kb_file", {"path": "app/billing/charge.py"}),
        ("kb_outline", {"path": "app/billing/charge.py"}),
        ("kb_impact", {"path": "app/billing/charge.py"}),
        ("kb_sync", {}),
        (
            "kb_update",
            {"id": "module/billing", "body": "## Purpose\n\nBills.\n", "read_hash": read_hash},
        ),
        ("kb_check", {}),
    ]

    _, *results = asyncio.run(session_calls(repo.root, calls))

    for (name, _), result in zip(calls, results, strict=True):
        assert not result.is_error, f"{name}: {result.content}"
        assert "next_steps" in payload(result), name
    assert payload(results[1])["source_hash_now"] == read_hash
    assert payload(results[3])["symbols"][0]["name"] == "charge"


def test_mcp_stdio_when_tool_fails_then_error_result_names_the_code(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    _, result = asyncio.run(session_calls(repo.root, [("kb_module", {"id": "nope"})]))

    assert result.is_error
    assert "NOT_FOUND" in result.content[0].text
