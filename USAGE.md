# Using Milepost

This guide separates **what works today** from **what is planned**. Milepost is early: it is not yet usable end to end. Where something is planned, the behavior described is the one specified in [SPEC.md](SPEC.md), and it may change before it is built.


## Try it as a Claude Code plugin (MVP)

The plugin lives in [plugin/](plugin/). For now it runs your local checkout of milepost, so there is nothing to publish or install from a registry. That means it must be loaded in place with `--plugin-dir` (below); installing it from a marketplace, which copies it elsewhere, needs the published release and does not work yet.

1. **One-time setup.** In this repository run `uv sync`. In the repository you want to try it on, put your model settings in a git-ignored `.env` file at its root (or export them in your shell):
   ```
   MILEPOST_MODEL=openrouter/<model slug>
   OPENROUTER_API_KEY=...
   ```
2. **Start Claude Code with the plugin loaded**, from the repository you want to try it on:
   ```
   claude --plugin-dir /path/to/milepost/plugin
   ```
   Approve the MCP server and hooks if Claude Code asks. `/mcp` should list `milepost` with ten `kb_*` tools.
3. **Run `/milepost:kb-init`.** It checks your environment, lists candidate modules, shows the files that would be sent to the model and the token estimate, asks once, then drafts a note for each module you keep.
4. **Review the drafts.** Read each note under `kb/modules/`, fix anything wrong, then approve it with `milepost review module/<id>` and commit `milepost.toml`, `kb/`, `.gitattributes` and `.github/workflows/milepost.yml`. (If `milepost` is not on your PATH, use `uv run --project /path/to/milepost milepost review module/<id>`.)
5. **Work normally.** At session start the agent is shown the module index. When it edits a covered file it is told which notes describe that file. When it tries to finish with a note out of date for files it changed, it is blocked once and told what to update. Its note edits are saved as `draft`, so run `milepost review` on them before merging.

What to expect on a first try:
- The first `kb_search` downloads the local embedding model (about 130 MB) and indexes the notes.
- Each hook starts `uv run`, which adds a fraction of a second to the first edit hook of a turn. If that bothers you, install milepost (`uv tool install /path/to/milepost`) and change the commands in `plugin/hooks/hooks.json` to plain `milepost hook ...`.
- If something looks wrong, run `milepost doctor` in the repository, and `claude plugin validate /path/to/milepost/plugin` for the plugin files.

## Contents

1. [Install](#install)
2. [Concepts in one minute](#concepts-in-one-minute)
3. [What works today](#what-works-today)
4. [The intended workflow](#the-intended-workflow)
5. [Command reference](#command-reference)
6. [Configuration](#configuration)
7. [Environment variables](#environment-variables)
8. [Exit codes](#exit-codes)

## Install

milepost is not published to PyPI yet. Run it from a checkout:

```bash
git clone <this repository> && cd <checkout>
uv sync --python 3.12
uv run milepost --help
```

To get a `milepost` command everywhere without activating the environment (it lives in its own isolated environment and does not touch your project's dependencies):

```bash
uv tool install --editable /path/to/this/checkout
```

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). The commands below assume you run them with `uv run milepost ...` from the checkout, or `milepost ...` after the tool install, and point at the repository you want to work on with `--repo`.

## Concepts in one minute

- A **module** is a named part of your repository, declared in `milepost.toml` as a set of file globs. Each module gets one **module note** (L2) at `kb/modules/<id>.md`.
- A **note** is a markdown file with YAML frontmatter. The frontmatter records which source files the note describes (`sources`) and a **source hash** of those files.
- A note is **stale** when the hash recorded in it no longer matches the hash of its source files as they are now.
- A note has a **status**: `draft` (written by a model or an agent, unreviewed) or `reviewed` (a person signed off). Agents are told to treat `draft` notes as unverified.
- `kb/INDEX.md` (L1) is generated from the module list and note statuses. You do not edit it by hand.
- Optional file notes (L3) and passage notes (L4) exist for details that don't fit a module note.

A note looks like this (see [templates/note.md.template](templates/note.md.template)):

```markdown
---
kb_schema: 1
id: module/services
level: L2
title: Services
status: reviewed
sources:
  - backend/app/services/**/*.py
source_hash: sha256:9f2c...        # never written by hand
related: [ai]
written_by: agent
written_at: 2026-10-07T09:12:00Z
---

## Purpose
...
## Invariants
...
## Gotchas
...
```

## What works today

Two commands are implemented. Both are read-only.

### `milepost scan`: find modules you haven't declared

Lists top-level directories under your source roots that no declared module covers. It works on any repository, with or without a `milepost.toml`, and never edits anything.

```bash
uv run milepost scan --repo /path/to/your/repo
uv run milepost scan --repo /path/to/your/repo --json
```

Source roots default to `src`, `app`, `backend/app`, `packages` and `apps`; change them with `[structure] roots` in `milepost.toml`. Each candidate is printed on one line as three tab-separated fields: a suggested id, the directory, and the source globs. For example, on a FastAPI backend:

```
services	backend/app/services	backend/app/services/**/*.py
tests	backend/app/tests	backend/app/tests/**/*.py
```

The scan proposes every directory that contains source files, including test directories, so you decide which candidates become modules. This is a safe first thing to try: it shows how milepost would carve up your repository.

### `milepost check`: find stale or invalid notes

Validates every note under `kb/` and reports:

| Finding | Severity | Meaning |
|---|---|---|
| `STALE_NOTE` | failure | The note's source files changed since it was written |
| `SOURCE_HASH_CONFLICT` | failure | A merge left the hash as `CONFLICT`; a person must review |
| `INDEX_DRIFT` | failure | `kb/INDEX.md` differs from a fresh render |
| `NOTE_INVALID`, `MISSING_KEY`, `INVALID_STATUS`, ... | failure | A note's frontmatter is missing or wrong |
| `MISSING_NOTE` | warning | A declared module has no note yet |
| `UNCOVERED_DIR` | warning | A source directory is covered by no module |
| `ORPHAN_NOTE` | warning | A file note describes a file that no longer exists |
| `DETAIL_NOTE_COUNT` | warning | Too many file and passage notes; prefer module notes |

```bash
uv run milepost check --repo /path/to/your/repo                 # human-readable
uv run milepost check --repo /path/to/your/repo --format json   # machine-readable
```

**CI mode** checks a pull request against its base branch:

```bash
uv run milepost check --repo . --ci --base origin/main
```

In CI mode a stale note fails only if a file it covers changed in the PR; stale notes the PR doesn't touch stay warnings, so existing debt doesn't block unrelated changes. A new source directory with no module, or a deleted file that a file note described, also fails. Any of these can be waived with a trailer in a commit message, and a waiver without a reason is an error:

```
KB-Waive: module/services prose is still accurate after this refactor
KB-Waive: dir:app/payments scratch code, a module comes later
```

Exit status is `0` when there are no failures, `1` when there is at least one, and `2` for a configuration or usage error. With `fail_on = "none"` in the config, the exit status is `0` regardless (report only).

### Why you can't build a knowledge base by hand yet

To have anything for `check` to examine, you would need to write `milepost.toml` and notes yourself, including a correct `source_hash`. The commands that produce and refresh notes (`init`, `draft`, `rehash`) are not built yet, and computing a hash by hand is error-prone. So for now, treat `scan` as the way to try milepost on a real repository, and `check` as something the test suite exercises.

## The intended workflow

Planned, from [SPEC.md](SPEC.md). None of this exists yet unless marked otherwise.

### One-time setup (planned: a single `/kb-init` command)

In the Claude Code plugin, `/kb-init` is the only command a developer runs. It:

1. Checks that the environment variables for drafting are set (see below), and tells you exactly which are missing if not.
2. Scans for candidate modules and shows you the list, the files that would be sent to the drafting model, and the estimated token count. You confirm once.
3. Writes `milepost.toml`, installs git hooks and the merge driver, adds the CI workflow, drafts one module note per module, and builds the search index.
4. Tells you the one step that needs a person: read each draft under `kb/modules/` and run `milepost review <id>` for each one that is correct. Then commit.

Drafted notes stay `draft` until you review them. Re-running `/kb-init` is safe and is also how you add a module later.

### Day to day (planned): what the agent does

With the plugin installed, the agent follows a fixed playbook ([SPEC.md](SPEC.md) section 12.5). In short:

- **Start of a task:** read the index, then the note for the module that owns the work, then only the files the note names. It does not grep the whole repository first.
- **Changing a file:** read the file, change it, ask which notes cover it, update each one through the MCP tool, then run the check.
- **New module:** add it to `milepost.toml`, ask the tool to draft its note, and leave it `draft` for a person to review.
- **A `CONFLICT` hash:** stop and tell a person. The agent does not resolve it.
- **Never** writes a `KB-Waive` trailer itself.

Reminders do not depend on the agent remembering: each tool response says what to do next, a plugin hook lists the covering notes when the agent edits a file, and a hook runs the check before the agent finishes.

### What a developer does (planned)

- Review the first draft of each module note once, and run `milepost review <id>`.
- Review note changes in pull requests alongside code changes. A note diff should state invariants and gotchas, not restate the code.
- When CI fails on a stale note, update the note. Use a waiver only when the note is still accurate, and give the reason.
- When a merge leaves a `CONFLICT` hash, read the note, fix the prose, and run `milepost rehash <id>` (planned).

## Command reference

"Works" means implemented and tested on `main`. "Branch" means built on the `m6-search-and-pilot` branch and not merged yet.

| Command | Purpose | State |
|---|---|---|
| `milepost scan [--repo P] [--json]` | List candidate modules no declared module covers | Works |
| `milepost check [--repo P] [--ci --base REF] [--format text\|json]` | Validate notes and detect staleness | Works |
| `milepost index [--rebuild]` | Write `INDEX.md` and build or update the search index | Branch |
| `milepost search QUERY [--level L] [--k N] [--json]` | Search the notes (keyword and vector) | Branch |
| `milepost init [--dry-run] [--modules ID,...] [--yes] [--force-config]` | Scaffold the knowledge base, declare the named modules, draft their notes, build the index | Works (also installs the git hooks unless `--no-hooks`) |
| `milepost draft ID [--force]` | Draft or redraft one module note | Works |
| `milepost review ID` | Mark a note as reviewed by you (records who and when) | Works |
| `milepost outline PATH [--json]` | Symbols and line ranges of one file, computed now | Works |
| `milepost impact PATH [--json]` | Importers and likely tests of one file, computed now | Works |
| `milepost sync [--base REF] [--json]` | What changed and which notes to update, and how | Works |
| `milepost status` | Per module: review state and unreviewed churn | Planned |
| `milepost report --base REF` | Review aid for a pull request | Planned |
| `milepost rehash ID [--yes]` | Record the current source hash on a note whose prose you have read | Works |
| `milepost hooks install\|uninstall` | Manage git hooks and the merge driver | Works |
| `milepost merge-driver` | Git merge driver for note files (called by git, not by you) | Works |
| `milepost serve` | Run the MCP server on stdio (ten `kb_*` tools); started by the plugin, not by hand | Works |
| `milepost hook post-edit\|stop` | Called by the Claude Code plugin hooks | Planned |
| `milepost doctor [--json]` | Report the environment milepost needs | Works |

Commands marked Planned currently print "not implemented yet" and exit with status 1. Every command accepts `--repo`; the default is the nearest ancestor directory containing `milepost.toml`.

## Configuration

`milepost.toml` lives at the repository root and is committed. [templates/milepost.toml.example](templates/milepost.toml.example) is a commented starting point. The sections:

| Section | Purpose |
|---|---|
| `[project]` | Project name and the notes folder (default `kb`) |
| `[modules.<id>]` | One table per module: `sources` (file globs, relative to the repo root), optional `title` and `related` |
| `[structure]` | `languages`, `ignore` globs, and `roots` where module candidates are looked for |
| `[index]` | Search index location and the embedding model and its dimension (these must agree) |
| `[draft]` | Drafting limits and files that are never sent to the model (`.env*`, keys, credentials) |
| `[check]` | `fail_on` (`stale` or `none`) and `max_detail_notes` |

Module ids are lowercase letters, digits, `_` and `-`. Globs must be relative and must not contain `..`. Invalid configuration is reported with the exact field path, for example `modules.Services.[key]: String should match pattern`, and exits with status 2.

## Environment variables

Needed only for drafting notes with a model (`draft`, `init`). Nothing is stored in `milepost.toml` or any committed file.

| Variable | Purpose |
|---|---|
| `MILEPOST_MODEL` | The model used to draft notes, in LiteLLM's format. For OpenRouter: `openrouter/<OpenRouter model slug>`. |
| The provider's own key variable | `OPENROUTER_API_KEY` for an `openrouter/...` model, `ANTHROPIC_API_KEY` for an Anthropic model. |

Set them in your shell, or put them in a `.env` file at the repository root (see [templates/.env.example](templates/.env.example)). milepost loads `.env` for `draft`, `init` and `doctor`; a variable already set in the shell wins. `milepost init` adds `.env` to `.gitignore`, and `milepost doctor` warns if a `.env` file exists that git does not ignore. Run `milepost doctor` to see what is missing; a missing variable exits with status 3.

Drafting sends the source of a module to the configured model provider. Files matching `draft.exclude` are never sent, a secret scan aborts a module if it finds credentials, and `init --dry-run` lists every file that would be sent before any network call.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | The check or operation found failures |
| 2 | Usage or configuration error |
| 3 | Environment error (missing dependency, no search index, unreadable repository) |
| 4 | LLM provider error |
