# kbmap Project Package

This folder is everything needed to start building `kbmap`, a Python tool that maintains an agent-driven codebase knowledge base.

Start here, then read in this order:

1. [PROPOSAL.md](PROPOSAL.md): why the project exists, alternatives, and the plan.
2. [SPEC.md](SPEC.md): what to build. Every file format, command, hash rule, and tool contract.
3. [TASKS.md](TASKS.md): the build order, with named test functions to write first.

## Folder contents

```
PROPOSAL.md          why and what (decision document)
SPEC.md              build specification
TASKS.md             milestones M0-M11 with tests and acceptance criteria
README.md            this file
templates/
  kbmap.toml.example         config template copied into user repos by `kbmap init`
  note.md.template           L2 note skeleton
  ci-kb-check.yml            GitHub Actions gate
  CLAUDE.md.snippet          rules to paste into a repo's CLAUDE.md
  plugin/                    Claude Code plugin wrapper files
```

## Quickstart for the implementer

```bash
uv init --package kbmap --python 3.12
# copy the dependency list from SPEC.md section 13 into pyproject.toml
# create the layout from SPEC.md section 15
uv run pytest            # tests fail first, per TASKS.md
```

## Settled decisions

These are fixed by SPEC.md section 0. Changing one requires updating SPEC.md first.

- Python 3.12+, distributed on PyPI, managed with `uv`.
- Apache-2.0 license.
- Markdown notes in git are the source of truth; the search index is a rebuildable cache.
- SQLite index in v1; Postgres deferred.
- The merge driver never recomputes `source_hash`; conflicts are surfaced for review.
- Claude Code integration is a plugin that runs the Python MCP server.

## Open items before release

- Verify the Claude Code plugin file layout against current documentation.
- Verify the codebase-memory-mcp query API before writing its adapter (deferred to v2).
- Choose the fastembed model and confirm its dimension matches the config.
- Pilot measurement (TASKS.md M11) decides whether to publish.
