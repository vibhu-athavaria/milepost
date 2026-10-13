# Milepost

**Git-native, drift-checked codebase memory for coding agents.**

Milepost keeps a small set of reviewed markdown notes about your code inside your own git repository. Each note records a fingerprint of the source files it describes, so when the code changes and the note doesn't, Milepost notices. Coding agents read the notes to find the right code quickly, and write back what they learn, so the next session, and the next teammate, doesn't start from zero. And because agents now change more code than any one person reads, the same notes, kept in pull requests, are how a developer still sees what changed in each module and which parts no person has reviewed.

> **Early development, unproven.** About half of the build plan is done (see [Status](#status)). The central claim, that agents using these notes read fewer files and spend fewer tokens, has **not been measured yet**. A pilot on a real repository decides whether this gets released. Features marked **(planned)** below are specified but not built.

## Contents

- [The problem](#the-problem)
- [The idea in one minute](#the-idea-in-one-minute)
- [What Milepost does](#what-milepost-does)
- [A walkthrough](#a-walkthrough)
- [What a note looks like](#what-a-note-looks-like)
- [What it adds to your repository](#what-it-adds-to-your-repository)
- [How it is different](#how-it-is-different)
- [What it does not do](#what-it-does-not-do)
- [FAQ](#faq)
- [Status](#status)
- [Documents, development, license](#documents)

## The problem

Coding agents learn a repository by searching it. Every session they grep, open files, and guess which ones matter. That has four costs:

- **Wasted context.** Files opened to find the right file are paid for in tokens and never used.
- **Missed code.** Keyword search misses the file that owns a behavior but doesn't share its name.
- **No continuity.** What an agent worked out about *why* a module behaves as it does is gone when the session ends. The next session rediscovers it.
- **No shared memory.** Each developer's agent builds its own understanding, and none of it reaches the team.
- **Lost grip.** With every developer using an agent on a big repository, no one reads all the code that changes. Mistakes an agent makes can pass through because no person had the context to spot them.

Tools that store this knowledge exist (see [How it is different](#how-it-is-different)). But a knowledge base that silently goes out of date is **worse than none**, because agents trust what they read. The hard part is not writing the notes. It is keeping them honest.

## The idea in one minute

1. **Write notes about modules, in git.** One markdown file per module: its purpose, entry points, the data it owns, the rules that must hold, and the traps. They live next to the code and are reviewed in pull requests.
2. **Fingerprint the source each note describes.** A note lists the files it covers and stores a hash of their contents.
3. **Notice drift.** `milepost check` recomputes the hash. If the code changed and the note didn't, that note is *stale*, and the check says so.
4. **Make staleness a build failure, not a surprise.** In CI, changing covered code without updating its note fails the pull request, unless someone records a reason.
5. **Let the agent do the typing.** Agents read the index, then the one relevant note, then only the files it points to. After a task they update the notes for what they changed. A human reviews the first draft of each note and then the note changes in pull requests.

The result is a memory that lives where your code lives, travels through your normal review process, and has a mechanical alarm for when it falls behind.

## What Milepost does

> **Legend.** Items marked **(works today)** are built and tested on `main`. **(on branch)** means built but not merged. **(planned)** means specified in [SPEC.md](SPEC.md), not built.

### 1. Keeps notes as plain markdown in git (works today)

Notes are markdown with a small YAML header, one file per module, committed with the code. There is no service to run and nothing to sync: notes move through push, pull request, merge and pull like any other file. The search index is a local cache that can always be rebuilt, never the source of truth.

Notes come in four levels, like the index of a book:

| Level | File | What it holds | Who writes it |
|---|---|---|---|
| L1 | `kb/INDEX.md` | One row per module, with a one-line purpose | Generated from the module notes |
| L2 | `kb/modules/<module>.md` | Purpose, entry points, a file map, owned data, invariants, gotchas | A model or the agent drafts it; a human reviews it; agents keep it current |
| L3 | `kb/files/<path>.md` | One file's gotchas (rare, exceptions only) | An agent or a person, only when a file has something a module note can't hold |
| L4 | `kb/passages/<slug>.md` | One passage (rare, exceptions only) | An agent or a person, on demand |

A note stores only what code can't tell you: purpose, contracts, rules, traps. **Per-file detail is not a note.** The functions in a file, their signatures and line ranges are read from the file when asked (`outline`), and who imports a file and which tests cover it are worked out from the code (`impact`). Facts that can be computed are never stored, so they can't go stale or add review work.

Most repositories need only L1 and L2. A module is declared in `milepost.toml` as a set of file globs, so *you* define what a module is. Milepost never infers it silently.

### 2. Detects when a note has drifted from its code (works today)

Each module note stores a `source_hash`: a digest over the files the note describes. It is defined precisely so two machines always agree:

1. Expand the note's globs against the repository root and keep regular files.
2. Sort the paths.
3. For each file, normalise line endings (CRLF and CR become LF, except in binary files) and take a SHA-256 of its contents.
4. Join `path<TAB>digest` lines and take a SHA-256 of that.

`milepost check` recomputes this for every note and compares. Any change to the contents of a covered file, including whitespace, makes the note stale. The hash proves *the note was written against the code as it is now*; it does not prove the prose is true. Human review of the draft is what vouches for the content (see [What it does not do](#what-it-does-not-do)).

### 3. Enforces freshness in CI (works today)

`milepost check --ci --base origin/main` judges a pull request by what it changes:

| Situation in the pull request | Result |
|---|---|
| A file covered by a note changed and the note still has the old hash | **Fails** |
| A note was already stale before the PR and the PR doesn't touch its files | Warning only (existing debt doesn't block unrelated work) |
| A new source directory appeared that no module covers | **Fails** |
| A file described by a file note was deleted | **Fails** |
| A module is declared but has no note yet | Warning only |
| A note's frontmatter is malformed, or a hash is left as `CONFLICT` | **Fails** |

A failure can be waived by writing a reason in a commit message trailer. A waiver with no reason is itself an error:

```
KB-Waive: module/services prose is still accurate after this refactor
KB-Waive: dir:app/payments scratch code, a module comes later
```

### 4. Gives agents a read path and a write path (planned)

Through an MCP server (`milepost serve`) agents get ten tools: an overview of the index, a module's note, the notes covering a given file, search, a note update, a check, drafting a note for a new module, and three that compute from the code as it is now: a file's **outline** (symbols with line ranges), a file's **impact** (importers and likely tests), and a **sync** (what changed and which notes to update).

- **Read path.** Index first, then the note for the module that owns the task, then the outline of the files it names so the agent reads only the lines it needs, and the impact of any file it will change. The agent does not grep the whole repository first.
- **Write path.** After the change the agent asks `sync` which notes need updating and how, re-reads the source, and updates each note. The update tool refuses a write unless the agent presents the hash it read, so a note can't be written against code the agent never fetched. Every agent edit leaves the note as `draft`, so a person has to review it again.
- **It doesn't rely on memory.** Every tool response says what to do next. In the Claude Code plugin, a hook lists the covering notes the moment the agent edits a file, and another runs the check before the agent is allowed to finish.

The exact scenario-by-scenario playbook (starting a task, changing a file, renaming one, adding a module, hitting a conflict) is in [SPEC.md](SPEC.md) section 12.5.

### 5. Searches the notes locally (works today)

`milepost search` runs a keyword search (SQLite FTS5) and a meaning-based search (local embeddings, no API key) over the notes and merges the two rankings, so both an exact term and a paraphrase find the right note. It covers the notes only, not your source code. Common filler words are kept out of the keyword half so they can't drown real matches. On a 20-note test knowledge base, 10 paraphrased questions each found their note in the top three.

### 6. Survives teams and merges (planned)

Notes are one file per module, so changes to different modules never conflict. When two branches both change a note's hash, a git merge driver never picks one. It writes `source_hash: CONFLICT`, and the check fails until a person reads the prose and runs `milepost rehash`. A merge can't quietly bless a stale note.

### 7. Sets up with one command (planned)

The `milepost init` command underneath (scaffold, declare modules, draft, index) is built on the `m7-draft-and-init` branch; the single `/kb-init` plugin command that wraps it is planned.

In the Claude Code plugin there is a single command, `/kb-init`. It checks the environment, shows you the candidate modules and the exact files that would be sent to the drafting model, and asks once. Then it writes the config, installs the git hooks and merge driver, adds the CI workflow, drafts one note per module, and builds the index. The only step left for a person is reading each draft and approving it with `milepost review <id>`. Drafts are marked `draft`, and agents are told to treat `draft` notes as unverified until then.

### 8. Handles your code carefully (on branch)

Drafting is the only step that sends source to a model, and only the model you configure. Files that look like secrets (`.env*`, keys, credentials) are never read for drafting, a scan aborts a module if it finds credentials in what it was about to send, and `milepost init --dry-run` lists every file before any network call. Model names and keys come from environment variables or a git-ignored `.env` file, never from committed files.

### 9. Keeps people in the loop (planned)

The aim is that a developer who did not write a change can still see what it did. Notes are in the pull request, so a reviewer reads a few lines of prose about each module instead of a long diff. On top of that:

- **Agent edits don't count as reviewed.** Only `milepost review`, run by a person, marks a note reviewed. An agent's edit flips it back to `draft`, and the flip shows in the diff.
- **`milepost status`** ranks modules by how much their code has changed since a person last reviewed their note, and how many of those commits look agent-authored.
- **`milepost report`** summarises a pull request: which notes changed, which are stale, which changed files nothing covers, and which changed files a note cites as an invariant or a gotcha. CI writes it to the job summary.
- **A named owner.** A one-line `CODEOWNERS` entry makes a person or team the required reviewer for `kb/`.

This shows people where to look. It doesn't find bugs or check that a note is true, and it can't make anyone read it.

## A walkthrough

*What a team's experience is meant to be. Steps after the first two are planned.*

**Setting up (once).** A developer installs the plugin and runs `/kb-init` on a FastAPI-and-React repository. It proposes `ai`, `api`, `core`, `models`, `services` and `tasks`; the developer drops `tests` and confirms. Six draft notes appear under `kb/modules/`. The developer reads each, corrects two, and approves them with `milepost review`. They commit `milepost.toml`, `kb/` and the CI workflow.

**An agent picks up a task** ("tutor answers sometimes repeat the same hint"). It reads the index, sees `ai` owns tutoring, and reads that note. The note's *Gotchas* section says hints are cached for ten minutes and the cache key ignores the student's last answer. The agent opens the two files the note names instead of searching the repository, finds the bug, and fixes it.

**It writes back.** Having changed a file in `ai`, the agent asks which notes cover it, re-reads the source, and updates the *Gotchas* line to say the cache key now includes the last answer. It runs the check, which passes, and commits the code and the note change together.

**A teammate's pull request** edits a file in `services` and forgets its note. CI runs `milepost check --ci`, reports `STALE_NOTE module/services`, and the pull request fails. The teammate (or their agent) updates the note, pushes, and it goes green.

**Two branches both touch a note.** The merge leaves `source_hash: CONFLICT` in the file. The check fails until someone reads the merged prose, fixes it, and runs `milepost rehash module/services`.

## What a note looks like

```markdown
---
kb_schema: 1
id: module/ai
level: L2
title: AI tutoring
status: reviewed                     # draft until a person signs off
sources:
  - backend/app/ai/**/*.py           # the files this note describes
source_hash: sha256:9f2c1a...        # filled in by the tool, never by hand
related: [services, core]
written_by: agent
written_at: 2026-10-07T09:12:00Z
---

## Purpose
Generates hints and explanations for students and decides when to escalate to a teacher.

## Entry points
- `backend/app/ai/tutor.py::answer_question`: called by the chat route.

## File map
- `tutor.py`: answers questions and decides when to escalate.
- `client.py`: the only place a model provider is called.
- `cache.py`: the hint cache.

## Owned data
- The `hint_cache` table: written only by this module.

## Invariants
- Every model call goes through `ai/client.py`; no route calls a provider directly.

## Gotchas
- Hints are cached for ten minutes. The cache key includes the student's last answer.
```

A full template is in [templates/note.md.template](templates/note.md.template).

## What it adds to your repository

```
your-repo/
  milepost.toml                 # which modules exist, and which files each covers
  kb/
    INDEX.md                    # L1: generated index of modules
    modules/                    # L2: one reviewed note per module
    files/  passages/           # L3, L4: optional detail notes
    .index/                     # local search cache (git-ignored, rebuildable)
  .gitattributes                # routes note merges through the merge driver
  .github/workflows/milepost.yml   # the CI gate
```

## How it is different

Several projects give coding agents better context. They differ in *where the knowledge lives* and *whether anything notices when it goes stale*. This table is based on each project's public description (links in the last column), checked in October 2026. Where a page doesn't say, the cell says "not stated" instead of guessing. Projects change, so please check the source.

| Approach | What the agent gets | Where knowledge lives | Does it detect notes drifting from code? | Source |
|---|---|---|---|---|
| Hand-written `CLAUDE.md` / `AGENTS.md` | Whatever a person wrote | A file in the repo | No. Nothing compares it to the code. | n/a |
| **codebase-memory-mcp** | A queryable graph of code structure (17 MCP tools, including architecture decision records) | A local SQLite database; an optional compressed snapshot can be committed | Not applicable to the graph (re-derived from code). ADR staleness: not stated. | [repo](https://github.com/DeusData/codebase-memory-mcp) |
| **CodeSeeker** | Hybrid search (keyword, vector, graph) over the codebase | A local `.codeseeker/` index | Not applicable (derived index) | [listing](https://mcpservers.org/servers/jghiringhelli/codeseeker) |
| **Serena** | IDE-like symbol-level retrieval and editing through language servers; also has a memory system | Memories: storage, authorship and staleness handling not stated on its main page | Not stated | [repo](https://github.com/oraios/serena) |
| **Aider repo map** | A compact map of the most relevant symbols, rebuilt for each request | Nothing is stored | Not applicable (rebuilt every time) | [docs](https://aider.chat/docs/repomap.html) |
| **Basic Memory** | General-purpose notes any assistant can read and write | Markdown files on disk, with a database index | Not stated. It is not specific to source code. | [repo](https://github.com/basicmachines-co/basic-memory) |
| **ByteRover / Cipher** | A persistent, hierarchical "context tree" shared across agents and teammates | A tree with its own git-style versioning, with optional cloud sync | Not stated | [docs](https://docs.byterover.dev/cipher/overview) |
| **Milepost** | Reviewed prose notes about *why* modules work as they do | Markdown in your own git repo | **Yes.** A source hash per note, a check command, and a CI gate | this repo |

In short: code-graph and retrieval tools tell an agent *what the code is*. Milepost's niche is the layer they don't claim to cover: the prose a team wants to keep ("this module owns these tables", "never call this before that"), plus a mechanism that stops that prose from quietly rotting. It is meant to sit **alongside** a code-graph tool, not replace one.

## What it does not do

- **It doesn't understand your code.** It doesn't answer questions about it, search source, or build a call graph. It parses files only to list their symbols, to find import relationships (for suggesting modules and for `impact`), and nothing deeper. `impact` is a static import graph and misses dynamic imports and framework wiring.
- **It doesn't find bugs.** It helps a person see where an agent changed things. A wrong change still has to be caught by review and tests.
- **It can't prove a note is true.** The hash shows a note was written against the current code (or that it wasn't). Whether the prose is *correct* depends on the review of the first draft and on the agents' later edits being reviewed in pull requests.
- **It can't catch drift outside a note's file set.** If a rule in a note depends on a file the note doesn't list, a change there won't flag the note. Keeping `sources` honest is part of the review.
- **Changes to covered files make a note stale, even trivial ones.** The fix is a re-read and a one-line update, but it is friction, and a fast-moving team may find the CI gate noisy. (Waivers and the "only fails if you touched covered files" rule exist for this.)
- **It isn't proven to pay off.** Small repositories likely don't need it: a good `CLAUDE.md` gets most of the benefit under a few hundred files. The pilot is designed to measure whether it helps on a real, larger one.
- **Language support is narrow in v1.** Import scanning covers Python, TypeScript and JavaScript. Hashing and notes are language-neutral.

## FAQ

**Does it send my code to a model?** Only when drafting a module note, and only to the model you configure. See [item 8](#8-handles-your-code-carefully-on-branch). Checking, indexing and searching run entirely on your machine.

**What if a note is wrong?** Treat it like documentation: correct it in a pull request. Agents are told to treat `draft` notes as unverified, to read the source before trusting a claim that matters, and never to edit the hash by hand.

**Does it replace `CLAUDE.md`?** No. `CLAUDE.md` is the right place for rules that apply everywhere. Milepost holds per-module knowledge and tells you when it has gone out of date. The plugin's rules are delivered by its own skill, so you don't need to paste them into `CLAUDE.md`.

**Why git and markdown instead of a database?** So the knowledge is reviewed, diffable, attributable and mergeable with the tools you already use, and can't be lost with a service. The database is only a cache for search.

**Which agents does it work with?** The agent interface is MCP, so any MCP-capable agent can read and write notes. The one-command setup, hooks and usage skill are being built for Claude Code first.

**What does it cost?** Drafting is the only paid step: roughly one model call per module, plus the cost of reading its source. `init --dry-run` shows the estimate first. Everything else is local.

**Why "milepost"?** A milepost is a fixed marker along a route that tells you where you are and how far you have come. Each note marks a point in the code and tells you whether you are still where it was written.

## Status

Built test-first. Milestones are defined in [TASKS.md](TASKS.md).

| Milestone | What | State |
|---|---|---|
| M0 to M2 | Package, config validation, note parse/validate/write | Done, on `main` |
| M3 | Source hash (identical across machines, checked against an independently computed value) | Done, on `main` |
| M4 | Python and TypeScript/JavaScript import scanners, module candidates, `milepost scan` | Done, on `main` |
| M5 | `milepost check`, including CI mode, waivers, and uncovered-directory detection | Done, on `main` |
| M5a | Baseline measurement on a real repository | Recorded, on `main` |
| M6 | `milepost index` and `milepost search` | Done, on `main` |
| M7 | Model drafting, `milepost init`, `milepost doctor`, `.env` support | Built, on the `m7-draft-and-init` branch (hooks step waits for M8) |
| M8 | Review and rehash commands, git hooks, merge driver | Done, on `main` |
| M8a | Computed context: `outline`, `impact`, `sync`, the one-line purpose in the index | Built, on the `m8a-computed-context` branch |
| M8b | Human visibility: `status`, `report`, unreviewed-churn warning, CODEOWNERS | Specified, not started |
| M9 | MCP server for agents (ten tools, model-mode drafting) | Done, on `main` |
| M10 | Claude Code plugin: one `/kb-init` command, hooks, usage skill | Built, on the `m10-plugin` branch; try it with [USAGE.md](USAGE.md) |
| M11 | Pilot: token cost, review effort, and the release decision | Not started |

**Not usable end to end yet.** Today you can run `milepost scan` and `milepost check`. The commands that create and maintain notes (`init`, `draft`, `review`, `rehash`) and the agent integration are still ahead. **[USAGE.md](USAGE.md)** covers installation, what works now, the intended workflow, and a command reference.

## Documents

| File | What it is |
|---|---|
| [USAGE.md](USAGE.md) | How to install and use it, and what works today |
| [PROPOSAL.md](PROPOSAL.md) | Why the project exists, the alternatives considered, and the plan |
| [SPEC.md](SPEC.md) | What to build: every file format, command, hash rule, and tool contract |
| [TASKS.md](TASKS.md) | The build order, with the named tests for each milestone |
| `templates/` | Config, note skeleton, CI workflow, CLAUDE.md snippet, and Claude Code plugin files that `init` copies into a repository |

## Development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --python 3.12
uv run pytest            # unit and integration tests
uv run ruff check        # lint
uv run mypy milepost     # strict type check
```

Tests are written before the code, and a milestone counts as done only when its acceptance commands have been run. The fixed decisions (Python 3.12+, Apache-2.0, notes in git as the source of truth, SQLite index in v1) are listed in [SPEC.md](SPEC.md) section 0. On Intel Macs, `pyproject.toml` constrains the resolver so a version of `onnxruntime` with a macOS x86_64 build is chosen.

## Naming

This project was developed under the working name `kbmap`, which turned out to be taken on PyPI by an unrelated keyboard-mapping tool, so it is now **Milepost**. Other, unrelated projects share the name (for instance a Swift build plugin and a small Claude Code memory project); this one is neither. Early commits and the workspace folder (`agent-kmap`) still use the old name.

## License

Apache-2.0. See [LICENSE](LICENSE).
