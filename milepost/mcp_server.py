"""The MCP server (SPEC section 11): tools registered over the logic in services/kb.py."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import AliasChoices, Field

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


# Agents guess parameter names, so each tool accepts the natural spellings. The first alias is
# the one the schema advertises.
ModuleArg = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("module", "id", "module_id", "name"),
        description="Module id, e.g. 'core' ('module/core' also works)",
    ),
]
PathArg = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("path", "file_path", "file", "filename"),
        description="Repo-relative file path",
    ),
]
_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITES_NOTES = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

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

    @server.tool(annotations=_READ_ONLY)
    def kb_overview() -> dict[str, Any]:
        """The module index (L1), counts of stale and draft notes, and the branch."""
        return _guard(lambda: kb.kb_overview(root))

    @server.tool(annotations=_READ_ONLY)
    def kb_module(module: ModuleArg) -> dict[str, Any]:
        """A module's note with source_hash_now, verify commands and related modules."""
        return _guard(lambda: kb.kb_module(root, module))

    @server.tool(annotations=_READ_ONLY)
    def kb_file(path: PathArg) -> dict[str, Any]:
        """The note(s) covering a file, each with a stale flag and source_hash_now."""
        return _guard(lambda: kb.kb_file(root, path))

    @server.tool(annotations=_READ_ONLY)
    def kb_search(
        query: Annotated[
            str,
            Field(
                validation_alias=AliasChoices("query", "q", "text", "search"),
                description="Words describing what you are looking for",
            ),
        ],
        limit: Annotated[int, Field(description="Most results to return (at most 10)")] = 5,
    ) -> dict[str, Any]:
        """Search the notes (keyword and meaning). At most 10 results. Updates the local
        search index first if notes changed."""
        return _guard(lambda: kb.kb_search(root, embedders, query, limit))

    @server.tool(annotations=_WRITES_NOTES)
    def kb_update(
        id: Annotated[
            str,
            Field(
                validation_alias=AliasChoices("id", "note_id", "note", "module"),
                description="Note id, e.g. 'module/core' (plain 'core' also works)",
            ),
        ],
        body: Annotated[str, Field(description="The note body in markdown, no frontmatter")],
        read_hash: Annotated[
            str | None, Field(description="source_hash_now from kb_module or kb_draft_module")
        ] = None,
    ) -> dict[str, Any]:
        """Save a module's note. Pass read_hash=source_hash_now from kb_module. Also creates the
        note of a declared module that has none. The note is saved as a draft until a person
        runs `milepost review`. Bodies that look like they contain a credential are rejected."""
        return _guard(lambda: kb.kb_update(root, id, body, read_hash, _now()))

    @server.tool(annotations=_READ_ONLY)
    def kb_check() -> dict[str, Any]:
        """Validate notes and report stale ones, the same as `milepost check`."""
        return _guard(lambda: kb.kb_check(root))

    @server.tool(annotations=_READ_ONLY)
    def kb_draft_module(
        module: ModuleArg,
        part: Annotated[
            int,
            Field(ge=1, description="Which part of the sources, from 1; the result says how many"),
        ] = 1,
    ) -> dict[str, Any]:
        """Get what you need to write the note for a module declared in milepost.toml: the
        instructions and the module's source files (minus excluded or credential-like files).
        Large modules come in parts: read every part (part=1, 2, ...) before writing. Writes
        nothing. Write the note yourself, then save it with kb_update using
        read_hash=source_hash_now."""
        return _guard(lambda: kb.kb_draft_module(root, module, part))

    @server.tool(annotations=_READ_ONLY)
    def kb_outline(path: PathArg) -> dict[str, Any]:
        """Symbols of one file with signatures and line ranges, computed now."""
        return _guard(lambda: kb.kb_outline(root, path))

    @server.tool(annotations=_READ_ONLY)
    def kb_impact(path: PathArg) -> dict[str, Any]:
        """Who imports a file and which tests likely cover it, computed now."""
        return _guard(lambda: kb.kb_impact(root, path))

    @server.tool(annotations=_READ_ONLY)
    def kb_sync(
        base: Annotated[
            str | None,
            Field(
                validation_alias=AliasChoices("base", "ref", "since"),
                description="Git ref to compare against; default: uncommitted changes",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Changed files and which notes to update, and how."""
        return _guard(lambda: kb.kb_sync(root, base))

    return server


def run_server(root: Path) -> None:
    build_server(root).run(transport="stdio")
