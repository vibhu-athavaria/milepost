"""The MCP server (SPEC section 11): tools registered over the logic in services/kb.py."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from milepost.config import Config
from milepost.embeddings import Embedder, default_embedder
from milepost.env import is_disabled
from milepost.services import kb

INSTRUCTIONS = (
    "Codebase knowledge base. Before searching code, call kb_overview, then kb_module for the "
    "module that owns your task, kb_outline for the files you will read, and kb_impact for the "
    "files you will change. After a change, call kb_sync and kb_update each note it lists, then "
    "kb_check. Every response has next_steps; follow them. You cannot mark a note reviewed; "
    "only a person can. kb_outline, kb_impact and kb_sync work in any git repository, even "
    "before a knowledge base exists."
)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _CachedEmbedders:
    """One embedder per model for the life of the server, so the model loads once."""

    def __init__(self) -> None:
        self._by_model: dict[tuple[str, int], Embedder | None] = {}

    def __call__(self, config: Config) -> Embedder | None:
        key = (config.index.embedding_model, config.index.embedding_dim)
        if self._by_model.get(key) is None:  # not cached while the extra is missing, so a later
            self._by_model[key] = default_embedder(*key)  # install is picked up without a restart
        return self._by_model[key]


PAUSED_INSTRUCTIONS = (
    "Milepost is paused (MILEPOST_DISABLED is set). It offers no tools in this session; work "
    "from the code directly."
)


def _guard(call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return call()
    except kb.KbToolError as error:
        raise ToolError(f"{error.code}: {error.message}") from error


def build_server(
    root: Path,
    embedder_for: Callable[[Config], Embedder | None] | None = None,
) -> MCPServer:
    if is_disabled():
        return MCPServer("milepost", instructions=PAUSED_INSTRUCTIONS)
    server = MCPServer("milepost", instructions=INSTRUCTIONS)
    embedders = embedder_for or _CachedEmbedders()

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
        """The note(s) covering a file, each with a stale flag and source_hash_now."""
        return _guard(lambda: kb.kb_file(root, path))

    @server.tool()
    def kb_search(query: str, limit: int = 5) -> dict[str, Any]:
        """Search the notes (keyword and meaning). At most 10 results. Updates the local
        search index first if notes changed."""
        return _guard(lambda: kb.kb_search(root, embedders, query, limit))

    @server.tool()
    def kb_update(id: str, body: str, read_hash: str | None = None) -> dict[str, Any]:
        """Save a module's note (id `module/<id>`). Pass read_hash=source_hash_now from
        kb_module. Also creates the note of a declared module that has none. The note is saved
        as a draft until a person runs `milepost review`. Bodies that look like they contain a
        credential are rejected."""
        return _guard(lambda: kb.kb_update(root, id, body, read_hash, _now()))

    @server.tool()
    def kb_check() -> dict[str, Any]:
        """Validate notes and report stale ones, the same as `milepost check`."""
        return _guard(lambda: kb.kb_check(root))

    @server.tool()
    def kb_draft_module(id: str) -> dict[str, Any]:
        """Get what you need to write the note for a module declared in milepost.toml: the
        instructions and the module's source files (minus excluded or credential-like files).
        Writes nothing. Write the note yourself, then save it with kb_update using
        read_hash=source_hash_now."""
        return _guard(lambda: kb.kb_draft_module(root, id))

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
