# Using Milepost

Milepost is an MVP. It works end to end as a Claude Code plugin loaded from a local checkout, and as a command-line tool. It is not published to PyPI, and nobody has yet measured whether it saves agent effort or keeps developers closer to their code (that is the pilot, TASKS M11). A few things are not built; they are listed in [What is not built yet](#what-is-not-built-yet).

## Contents

1. [Try it as a Claude Code plugin](#try-it-as-a-claude-code-plugin)
2. [Install the command line tool](#install-the-command-line-tool)
3. [Concepts in one minute](#concepts-in-one-minute)
4. [Day to day](#day-to-day)
5. [Command reference](#command-reference)
6. [What `check` reports](#what-check-reports)
7. [Configuration](#configuration)
8. [Environment variables](#environment-variables)
9. [Exit codes](#exit-codes)
10. [What is not built yet](#what-is-not-built-yet)

## Try it as a Claude Code plugin

The plugin lives in [plugin/](plugin/). For now it runs your local checkout of milepost, so there is nothing to publish or install from a registry. That means it must be loaded in place with `--plugin-dir` (below). Installing it from a marketplace, which copies it elsewhere, needs the published release and does not work yet.

1. **One-time setup.** In the milepost checkout run `uv sync --python 3.12`. In the repository you want to try it on, put your model settings in a git-ignored `.env` file at its root (or export them in your shell):
   ```
   MILEPOST_MODEL=openrouter/<model slug>
   OPENROUTER_API_KEY=...
   ```
2. **Start Claude Code with the plugin loaded**, from the repository you want to try it on:
   ```
   claude --plugin-dir /path/to/milepost/plugin
   ```
   Approve the MCP server and hooks if Claude Code asks. `/mcp` should list `milepost` with ten `kb_*` tools.
3. **Run `/milepost:kb-init`.** It checks your environment, lists candidate modules, shows the files that would be sent to the model and the token estimate, asks once, then drafts a note for each module you keep. It also installs the git hooks and merge driver and writes the CI workflow.
4. **Review the drafts.** Read each note under `kb/modules/`, fix anything wrong, then approve it with `milepost review module/<id>` and commit `milepost.toml`, `kb/`, `.gitattributes` and `.github/workflows/milepost.yml`. (If `milepost` is not on your PATH, use `uv run --project /path/to/milepost milepost review module/<id>`.)
5. **Work normally.** At session start the agent is shown the module index. When it edits a covered file it is told which notes describe that file. When it tries to finish with a note out of date for files it changed, it is blocked once and told what to update. Its note edits are saved as `draft`, so run `milepost review` on them before merging.

What to expect on a first try:
- The first `kb_search` downloads the local embedding model (about 130 MB) and indexes the notes.
- Each hook starts `uv run`, which adds a fraction of a second to the hook. If that bothers you, install milepost (`uv tool install --editable /path/to/milepost`) and change the commands in `plugin/hooks/hooks.json` to plain `milepost hook ...`.
- The CI workflow that `init` writes installs milepost from PyPI (`uv tool install "milepost==<version>"`). Until milepost is published, that step fails in CI. Edit `.github/workflows/milepost.yml` to install from your checkout or a git URL, or leave the workflow out of your first trial.
- Drafting sends a module's source to your model provider. Run `/milepost:kb-init` only on code you are allowed to send, and read the dry-run list it shows first.
- If something looks wrong, run `milepost doctor` in the repository, and `claude plugin validate /path/to/milepost/plugin` for the plugin files.

## Install the command line tool

```bash
git clone <this repository> && cd <checkout>
uv sync --python 3.12
uv run milepost --help
```

To get a `milepost` command everywhere without activating the environment (it lives in its own isolated environment and does not touch your project's dependencies):

```bash
uv tool install --editable /path/to/this/checkout
```

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). Every command accepts `--repo`; the default is the nearest ancestor directory containing `milepost.toml`.

## Concepts in one minute

- A **module** is a named part of your repository, declared in `milepost.toml` as a set of file globs. Each module gets one **module note** (L2) at `kb/modules/<id>.md`.
- A **note** is a markdown file with YAML frontmatter. The frontmatter records which source files the note describes (`sources`) and a **source hash** of those files.
- A note is **stale** when the hash recorded in it no longer matches the hash of its source files as they are now.
- A note has a **status**: `draft` (written by a model or an agent, unreviewed) or `reviewed` (a person signed off with `milepost review`). Every agent edit sets a note back to `draft`. Agents are told to treat `draft` notes as unverified.
- `kb/INDEX.md` (L1) is generated from the module notes: one row per module with its purpose and status. You do not edit it by hand.
- Optional file notes (L3) and passage notes (L4) are rare, for details that do not fit a module note. Per-file detail (functions, line ranges) is not a note: `milepost outline` reads it from the file, and `milepost impact` works out who imports a file and which tests cover it.

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
reviewed_by: Jane Doe <jane@example.com>
reviewed_at: 2026-10-08T14:00:00Z
---

## Purpose
...
## Entry points
...
## File map
...
## Owned data
...
## Invariants
...
## Gotchas
...
```

## Day to day

**What the agent does.** With the plugin, the agent follows a fixed playbook ([SPEC.md](SPEC.md) section 12.5) through the `kb_*` tools:
- *Start of a task:* read the index, then the note for the module that owns the work, then the outline of the files it will read and the impact of the files it will change. It does not grep the whole repository first.
- *After a change:* `kb_sync` lists the notes to update and how; the agent re-reads the source and updates each through `kb_update`, then runs `kb_check`.
- *New module:* add it to `milepost.toml`, call `kb_draft_module`, and leave the note `draft` for a person.
- *A `CONFLICT` hash:* stop and tell a person. The agent never rehashes, never marks a note reviewed, and never writes a `KB-Waive` trailer.

Reminders do not depend on the agent remembering: each tool response says what to do next, a hook shows the index at session start, another lists the covering notes when the agent edits a file, and a third runs a check before the agent finishes.

**What a developer does.**
- Review the first draft of each module note once, then run `milepost review module/<id>`.
- Review note changes in pull requests alongside code changes. A note diff should state invariants and gotchas, not restate the code. An agent's edit shows as a flip from `reviewed` to `draft`.
- When CI fails on a stale note, update the note. Use a waiver only when the note is still accurate, and give the reason.
- When a merge leaves a `CONFLICT` hash, read the merged prose, fix it, and run `milepost rehash module/<id>`.

## Command reference

| Command | Purpose |
|---|---|
| `milepost init [--dry-run] [--modules ID,...] [--yes] [--agent-mode] [--force-config] [--no-hooks]` | Scaffold the knowledge base, declare the named modules, draft their notes, install the git hooks, build the index. Writes nothing and sends nothing with `--dry-run` |
| `milepost scan [--json]` | List candidate modules that no declared module covers. Read-only |
| `milepost check [--ci --base REF] [--format text\|json] [--no-churn]` | Validate notes and detect staleness. Exit 1 on failures. `--no-churn` skips the slower unreviewed-churn warning |
| `milepost draft ID [--force]` | Draft or redraft one module note with the configured model |
| `milepost review NOTE_ID` | Mark a note reviewed by you (records your git identity and the time). Refuses a stale or `CONFLICT` note |
| `milepost rehash NOTE_ID [--yes]` | Record the current source hash on a note whose prose you have just read |
| `milepost index [--rebuild]` | Write `INDEX.md` and build or update the local search index |
| `milepost search QUERY [--level L] [--k N] [--json]` | Search the notes (keyword and meaning) |
| `milepost outline PATH [--json]` | Symbols, signatures and line ranges of one file, computed now (Python, TypeScript, JavaScript) |
| `milepost impact PATH [--json]` | Files that import a file and the tests likely to cover it, computed now. A static import graph |
| `milepost sync [--base REF] [--json]` | What changed and which notes to update, and how |
| `milepost hooks install\|uninstall` | Manage the git hooks and the merge driver. Never overwrites a hook it did not write |
| `milepost status [--json]` | Per module: who reviewed its note, and how many lines and commits (and how many agent-authored) have changed since. Never-reviewed modules first |
| `milepost report --base REF [--format markdown\|json]` | A review aid for a change range: notes changed, stale notes, uncovered files, invariants and gotchas that cite changed files, unreviewed churn. Always exits 0 |
| `milepost doctor [--json]` | Report the environment milepost needs. Exit 3 when a drafting variable is missing |
| `milepost serve` | Run the MCP server on stdio. Started by the plugin, not by hand |
| `milepost hook session-start\|post-edit\|stop` | Called by the plugin hooks, with JSON on stdin. Always exit 0 |
| `milepost merge-driver` | Git merge driver for note files. Called by git, not by you |

The git hooks `milepost hooks install` adds are `post-merge` and `post-checkout` (run `index`, never block) and `pre-commit` (runs `check --no-churn`, which blocks on failures; bypass with `git commit --no-verify`).

## What `check` reports

| Finding | Severity | Meaning |
|---|---|---|
| `STALE_NOTE` | failure | The note's source files changed since it was written |
| `SOURCE_HASH_CONFLICT` | failure | A merge left the hash as `CONFLICT`; a person must review |
| `INDEX_DRIFT` | failure | `kb/INDEX.md` differs from a fresh render. Run `milepost index`. Editing a note's Purpose changes the index, so this follows any such edit that did not go through `kb_update` or `review` |
| `NOTE_INVALID`, `MISSING_KEY`, `INVALID_STATUS`, `ID_PATH_MISMATCH`, ... | failure | A note's frontmatter is missing or wrong |
| `MISSING_NOTE` | warning | A declared module has no note yet |
| `UNCOVERED_DIR` | warning | A source directory is covered by no module |
| `ORPHAN_NOTE` | warning | A file note describes a file that no longer exists |
| `DETAIL_NOTE_COUNT` | warning | Too many file and passage notes; prefer module notes |
| `CITATION_BROKEN` | warning | A note cites (in backticks, in Entry points, File map, Invariants or Gotchas) a file that is not in the repository, or a `file::symbol` whose name does not appear in the file. Lenient on purpose: it flags only what is clearly absent. A cheap check for invented details; it cannot tell whether a true citation supports the claim |
| `UNREVIEWED_CHURN` | warning | A reviewed note's source files changed by more than `visibility.churn_warn_lines` since the review. Never a failure |

**CI mode** (`milepost check --ci --base origin/main`) judges a pull request by what it changes. A stale note fails only if a file it covers changed in the PR; stale notes the PR does not touch stay warnings, so existing debt does not block unrelated changes. A new source directory with no module, or a deleted file that a file note described, also fails. Any of these can be waived with a trailer in a commit message, and a waiver without a reason is an error:

```
KB-Waive: module/services prose is still accurate after this refactor
KB-Waive: dir:app/payments scratch code, a module comes later
```

With `fail_on = "none"` in the config, the exit status is `0` regardless (report only).

## Configuration

`milepost.toml` lives at the repository root and is committed. [templates/milepost.toml.example](templates/milepost.toml.example) is a commented starting point. The sections:

| Section | Purpose |
|---|---|
| `[project]` | Project name and the notes folder (default `kb`) |
| `[modules.<id>]` | One table per module: `sources` (file globs, relative to the repo root), optional `title`, `related`, and `verify` (commands that check the module, shown to agents; write them yourself) |
| `[structure]` | `languages`, `ignore` globs, and `roots` where module candidates are looked for |
| `[index]` | Search index location and the embedding model and its dimension (these must agree) |
| `[draft]` | `mode` (`model` or `agent`), drafting limits (`max_source_bytes`, default 200000 per module; larger modules are partly sent as outlines and the note says so) and files that are never sent to the model (`**/.env*`, keys, credentials) |
| `[check]` | `fail_on` (`stale` or `none`) and `max_detail_notes` |
| `[visibility]` | `agent_trailers` (regexes that mark a commit as agent-authored, default: Claude Code's `Co-Authored-By ... noreply@anthropic.com` trailer and its "Generated with Claude Code" line) and `churn_warn_lines` (default 1000) |

Module ids are lowercase letters, digits, `_` and `-`. Globs must be relative and must not contain `..`. Invalid configuration is reported with the exact field path and exits with status 2.

## Environment variables

Needed only to draft notes with a separate model (`draft`, `init`, and `kb_draft_module` in model mode). In **agent mode** (`milepost init --agent-mode`, or `[draft] mode = "agent"`) your coding agent writes the notes itself, so no model or key is needed. Nothing is stored in `milepost.toml` or any committed file.

| Variable | Purpose |
|---|---|
| `MILEPOST_MODEL` | The model used to draft notes, in LiteLLM's format. For OpenRouter: `openrouter/<OpenRouter model slug>`. |
| The provider's own key variable | `OPENROUTER_API_KEY` for an `openrouter/...` model, `ANTHROPIC_API_KEY` for an Anthropic model. |

Set them in your shell, or put them in a `.env` file at the repository root (see [templates/.env.example](templates/.env.example)). milepost loads `.env` for `draft`, `init`, `doctor` and `serve`; a variable already set in the shell wins. `milepost init` adds `.env` to `.gitignore`, and `milepost doctor` warns if a `.env` file exists that git does not ignore. Run `milepost doctor` to see what is missing; a missing variable exits with status 3. `doctor` also warns when a git hook was written by an older milepost (rerun `milepost hooks install`).

Drafting sends the source of a module to the configured model provider. Files matching `draft.exclude` are never sent, a secret scan aborts a module if it finds credentials, and `init --dry-run` lists every file that would be sent before any network call.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | The check or operation found failures |
| 2 | Usage or configuration error |
| 3 | Environment error (missing dependency or variable, no search index, unreadable repository) |
| 4 | LLM provider error |

## What is not built yet

- **Installing the plugin from a marketplace**, `uvx milepost`, and a working generated CI workflow: all need a published release (M11).
- **Other agents:** the MCP server is standard, and `templates/AGENTS.md.snippet` carries the playbook, but only Claude Code has been considered and nothing has been tested with another agent.
- **Measurement:** whether any of this saves tokens or helps reviewers is untested.
