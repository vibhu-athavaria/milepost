"""The MCP server (SPEC section 11): tools registered over the logic in services/kb.py."""

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from milepost.config import Config
from milepost.embeddings import Embedder, FastembedEmbedder
from milepost.llm.client import LiteLlmClient, LlmClient
from milepost.services import kb

INSTRUCTIONS = (
    "Codebase knowledge base. Before searching code, call kb_overview, then kb_module for the "
    "module that owns your task, kb_outline for the files you will read, and kb_impact for the "
    "files you will change. After a change, call kb_sync and kb_update each note it lists, then "
    "kb_check. Every response has next_steps; follow them. You cannot mark a note reviewed; "
    "only a person can."
)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_embedder(config: Config) -> Embedder:
    return FastembedEmbedder(config.index.embedding_model, config.index.embedding_dim)


def _guard(call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return call()
    except kb.KbToolError as error:
        raise ToolError(f"{error.code}: {error.message}") from error


def build_server(
    root: Path,
    embedder_for: Callable[[Config], Embedder] = _default_embedder,
    client: LlmClient | None = None,
) -> MCPServer:
    server = MCPServer("milepost", instructions=INSTRUCTIONS)
    llm = client or LiteLlmClient()

    @server.tool()
    def kb_overview() -> dict[str, Any]:
        """The module index (L1), counts of stale and draft notes, and the branch."""
        return _guard(lambda: kb.kb_overview(root))

    @server.tool()
    def kb_module(
        id: Annotated[str, Field(description="Module id, e.g. 'services'")],
    ) -> dict[str, Any]:
        """A module's note with source_hash_now, verify commands and related modules."""
        return _guard(lambda: kb.kb_module(root, id))

    @server.tool()
    def kb_file(
        path: Annotated[str, Field(description="Repo-relative file path")],
    ) -> dict[str, Any]:
        """Every note covering a file, each with source_hash_now and a stale flag."""
        return _guard(lambda: kb.kb_file(root, path))

    @server.tool()
    def kb_search(query: str, level: str | None = None, limit: int = 5) -> dict[str, Any]:
        """Search the notes (keyword and meaning). At most 10 results."""
        return _guard(lambda: kb.kb_search(root, embedder_for, query, level, limit))

    @server.tool()
    def kb_update(id: str, body: str, read_hash: str | None = None) -> dict[str, Any]:
        """Write a note. For L2 and L3, pass read_hash=source_hash_now from kb_module or
        kb_file. The note is saved as a draft; a person must run `milepost review`."""
        return _guard(lambda: kb.kb_update(root, id, body, read_hash, _now()))

    @server.tool()
    def kb_check() -> dict[str, Any]:
        """Validate notes and report stale ones, the same as `milepost check`."""
        return _guard(lambda: kb.kb_check(root))

    @server.tool()
    def kb_draft_module(id: str) -> dict[str, Any]:
        """Draft the note for a module already declared in milepost.toml. Sends the module's
        source to the configured LLM provider."""
        return _guard(lambda: kb.kb_draft_module(root, id, llm, os.environ, _now(), time.sleep))

    @server.tool()
    def kb_outline(path: str) -> dict[str, Any]:
        """Symbols of one file with signatures and line ranges, computed now."""
        return _guard(lambda: kb.kb_outline(root, path))

    @server.tool()
    def kb_impact(path: str) -> dict[str, Any]:
        """Who imports a file and which tests likely cover it, computed now."""
        return _guard(lambda: kb.kb_impact(root, path))

    @server.tool()
    def kb_sync(base: str | None = None) -> dict[str, Any]:
        """Changed files and which notes to update, and how."""
        return _guard(lambda: kb.kb_sync(root, base))

    return server


def run_server(root: Path) -> None:
    build_server(root).run(transport="stdio")
