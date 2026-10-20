"""Starts `milepost serve` as a subprocess and talks to it over stdio like a real client."""

import asyncio
import json
import os
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


async def session_calls(
    root: Path, calls: list[tuple[str, dict[str, Any]]], env: dict[str, str] | None = None
) -> list[Any]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "milepost", "serve", "--repo", str(root)],
        env={**os.environ, **env} if env else None,
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


def test_mcp_stdio_when_milepost_disabled_then_server_offers_no_tools(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    (names,) = asyncio.run(session_calls(repo.root, [], env={"MILEPOST_DISABLED": "1"}))

    assert names == set()


def test_mcp_stdio_when_tools_listed_then_every_parameter_has_a_description(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    async def listed() -> list[Any]:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "milepost", "serve", "--repo", str(repo.root)]
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return list((await session.list_tools()).tools)

    for tool in asyncio.run(listed()):
        for name, schema in tool.input_schema.get("properties", {}).items():
            assert schema.get("description"), (tool.name, name)


def test_mcp_stdio_when_an_agent_guesses_natural_argument_names_then_every_call_succeeds(
    tmp_path: Path,
) -> None:
    """Agents guess parameter names (`module`, `file_path`, `q`). Each tool must accept them."""
    repo = make_repo(tmp_path)
    repo.add_module(
        "other", ["app/other/**/*.py"], {"app/other/x.py": "def run():\n    return 1\n"}, False
    )
    repo.commit("add other")
    read_hash = repo.hash_of(["app/billing/**/*.py"])
    calls: list[tuple[str, dict[str, Any]]] = [
        ("kb_module", {"module": "billing"}),
        ("kb_module", {"id": "module/billing"}),
        ("kb_module", {"module_id": "billing"}),
        ("kb_draft_module", {"module": "other"}),
        ("kb_draft_module", {"id": "other"}),
        ("kb_draft_module", {"module_id": "module/other", "part": 1}),
        ("kb_file", {"file_path": "app/billing/charge.py"}),
        ("kb_outline", {"file": "app/billing/charge.py"}),
        ("kb_impact", {"filename": "app/billing/charge.py"}),
        ("kb_search", {"q": "billing"}),
        ("kb_sync", {"ref": "HEAD"}),
        ("kb_sync", {"since": "HEAD"}),
        ("kb_sync", {"base": "HEAD"}),
        ("kb_module", {"name": "billing"}),
        ("kb_search", {"text": "billing"}),
        ("kb_search", {"search": "billing"}),
        ("kb_search", {"query": "billing", "limit": 3}),
        (
            "kb_update",
            {"note_id": "billing", "body": "## Purpose\n\nBills.\n", "read_hash": read_hash},
        ),
    ]

    _, *results = asyncio.run(session_calls(repo.root, calls))

    for (name, arguments), result in zip(calls, results, strict=True):
        assert not result.is_error, f"{name} {arguments}: {result.content}"


def test_mcp_stdio_when_listing_tools_then_read_only_ones_say_so(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    async def listed() -> dict[str, Any]:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "milepost", "serve", "--repo", str(repo.root)]
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return {t.name: t.annotations for t in (await session.list_tools()).tools}

    annotations = asyncio.run(listed())

    assert annotations["kb_update"].read_only_hint is False
    assert annotations["kb_update"].destructive_hint is False
    for name in EXPECTED_TOOLS - {"kb_update"}:
        assert annotations[name].read_only_hint is True, name
