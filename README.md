# kbmap

**Git-native, drift-checked codebase memory for coding agents.**

> **Working name.** The name `kbmap` is already taken on PyPI (by an unrelated Linux keyboard-mapping utility), so this project will be renamed before any release. See [Naming](#naming).

> **Status: early development, unproven.** Roughly half of the build plan is done (see [Status](#status)). The central claim, that agents using these notes read fewer files and spend fewer tokens, has not been measured yet. A pilot on a real repository decides whether this is published at all.

## The problem

Coding agents learn a repository by searching it. Every session they grep, open files, and guess which ones matter. That has four costs:

- **Wasted context.** Files opened to find the right file are paid for in tokens and never used.
- **Missed code.** Keyword search misses the file that owns a behavior but doesn't share its name.
- **No continuity.** What an agent learned about why a module works the way it does is gone when the session ends.
- **No shared memory.** Each developer's agent builds its own understanding, and none of it reaches the team.

Tools that store this knowledge exist, but a knowledge base that silently goes out of date is worse than none, because agents trust it.

## What kbmap does

kbmap keeps a small set of **markdown notes about your code, committed in your repository**, and makes it hard for those notes to drift away from the code they describe.

- **Notes live in git.** Plain markdown with YAML frontmatter, one note per module, reviewed in pull requests like any other file. The search index is a local, rebuildable cache. It is never the source of truth.
- **Every note is tied to its source.** A note records a hash of the source files it describes. `kbmap check` recomputes the hash and reports notes whose sources changed since they were written.
- **CI enforces it.** On a pull request, a change to source covered by a note fails the check unless the note was updated in the same PR (or a reasoned waiver is recorded in the commit).
- **Agents read top-down and write back.** An agent reads the index, then the module note, then only the files the note points to. After a task, it updates the notes for what it changed. This is done through MCP tools, and plugin hooks remind the agent so it does not depend on remembering.
- **Merges never bless a stale note.** If two branches both change a note's hash, the merge driver writes a `CONFLICT` marker and the check fails until a person reviews it.

### How the notes are organized

Like the index of a book, from coarse to fine:

| Level | What | Written by |
|---|---|---|
| L1 | `kb/INDEX.md`: one row per module | Generated |
| L2 | `kb/modules/<module>.md`: purpose, entry points, owned data, invariants, gotchas | Drafted by an LLM, reviewed by a human, then kept current by agents |
| L3 | `kb/files/<path>.md`: one file, optional | Agent, only when a file has something the module note can't hold |
| L4 | `kb/passages/<slug>.md`: one passage, optional | Agent, on demand |

Structure (imports, call paths) is derived by a deterministic scan. Only prose (purpose, invariants, gotchas) is authored, and prose is the part that can drift, which is why it is the part that carries a hash.

## How it is different

Several projects give coding agents better context. They differ in *where the knowledge lives* and *whether anything notices when it goes stale*. This table is based on each project's public description (links in the last column), checked in October 2026. Where a page does not say, the cell says "not stated" rather than guessing, and projects change, so please check the source.

| Approach | What the agent gets | Where knowledge lives | Does it detect notes drifting from code? | Source |
|---|---|---|---|---|
| Hand-written `CLAUDE.md` / `AGENTS.md` | Whatever a person wrote | A file in the repo | No. Nothing compares it to the code. | n/a |
| **codebase-memory-mcp** | A queryable graph of code structure (17 MCP tools, including architecture decision records) | A local SQLite database; an optional compressed snapshot can be committed | Not applicable to the graph (it is re-derived from code). ADR staleness: not stated. | [repo](https://github.com/DeusData/codebase-memory-mcp) |
| **CodeSeeker** | Hybrid search (keyword + vector + graph) over the codebase | A local `.codeseeker/` index | Not applicable (derived index) | [listing](https://mcpservers.org/servers/jghiringhelli/codeseeker) |
| **Serena** | IDE-like symbol-level retrieval and editing through language servers; also has a memory system | Memories: storage, authorship and staleness handling not stated on its main page | Not stated | [repo](https://github.com/oraios/serena) |
| **Aider repo map** | A compact map of the most relevant symbols, rebuilt for each request | Nothing is stored | Not applicable (rebuilt every time) | [docs](https://aider.chat/docs/repomap.html) |
| **Basic Memory** | General-purpose notes any assistant can read and write | Markdown files on disk, with a database index | Not stated. It is not specific to source code. | [repo](https://github.com/basicmachines-co/basic-memory) |
| **ByteRover / Cipher** | A persistent, hierarchical "context tree" shared across agents and teammates | A tree with its own git-style versioning, with optional cloud sync | Not stated | [docs](https://docs.byterover.dev/cipher/overview) |
| **kbmap** | Reviewed prose notes about *why* modules work as they do | Markdown in your own git repo | **Yes.** Per-note source hash, a check command, and a CI gate | this repo |

In short: code-graph and retrieval tools tell an agent *what the code is*. kbmap's niche is the layer they don't claim to cover, the prose a team wants to keep ("this module owns these tables", "never call this before that"), plus a mechanism that stops that prose from quietly rotting. It is meant to sit **alongside** a code-graph tool, not replace one. Its notes are for reading by id, so its search covers notes only, not source code.

What kbmap does **not** do: parse or answer questions about your code on its own, replace tests or documentation, or guarantee a note is *correct*. The hash proves a note was written against the code as it is now (or flags that it wasn't), not that the prose is true. Human review of the first draft of each module note is what vouches for the content.

## Status

Built test-first. Milestones are defined in [TASKS.md](TASKS.md).

| Milestone | What | State |
|---|---|---|
| M0 to M2 | Package, config validation, note parse/validate/write | Done, on `main` |
| M3 | Source hash (identical across machines, checked against an independently computed value) | Done, on `main` |
| M4 | Python and TypeScript/JavaScript import scanners, module candidates, `kbmap scan` | Done, on `main` |
| M5 | `kbmap check`, including CI mode, waivers, and uncovered-directory detection | Done, on `main` |
| M6 | `kbmap index` and `kbmap search` (keyword + vector, merged by rank fusion) | Built on the `m6-search-and-pilot` branch, not merged |
| M7 | LLM drafting of module notes and `kbmap init` | Not started |
| M8 | Review/rehash commands, git hooks, merge driver | Not started |
| M9 | MCP server for agents | Not started |
| M10 | Claude Code plugin (one `/kb-init` command, hooks, usage skill) | Not started |
| M11 | Pilot measurement and release decision | Not started |

**Not usable end to end yet.** Today you can run `kbmap scan` and `kbmap check`. The commands that create and maintain notes (`init`, `draft`, `review`, `rehash`) and the agent integration are still ahead. [USAGE.md](USAGE.md) separates what works now from what is planned.

## Using it

See **[USAGE.md](USAGE.md)** for installation, what works today, the intended day-to-day workflow, and a command reference.

## Documents

| File | What it is |
|---|---|
| [PROPOSAL.md](PROPOSAL.md) | Why the project exists, the alternatives considered, and the plan |
| [SPEC.md](SPEC.md) | What to build: every file format, command, hash rule, and tool contract |
| [TASKS.md](TASKS.md) | The build order, with the named tests for each milestone |
| [USAGE.md](USAGE.md) | How to use it |
| `templates/` | Config, note skeleton, CI workflow, CLAUDE.md snippet, and Claude Code plugin files that `init` will copy into a repository |

## Development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --python 3.12
uv run pytest            # unit and integration tests
uv run ruff check        # lint
uv run mypy kbmap        # strict type check
```

Tests are written before the code, and a milestone counts as done only when its acceptance commands have been run. The decisions that are fixed (Python 3.12+, Apache-2.0, notes in git as the source of truth, SQLite index in v1) are listed in [SPEC.md](SPEC.md) section 0.

On Intel Macs, `pyproject.toml` constrains the resolver so that a version of `onnxruntime` with a macOS x86_64 build is chosen.

## Naming

`kbmap` is a placeholder. The PyPI project `kbmap` already exists (an unrelated keyboard-mapping tool), so the package cannot be published under that name. The new name will replace the package name, the CLI command, the `kbmap.toml` config file, and the plugin name. Until then, everything here uses `kbmap`.

## License

Apache-2.0. See [LICENSE](LICENSE).
