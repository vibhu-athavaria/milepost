# milepost Specification

Status: v1 spec, as built and as trimmed (see "The trim" in TASKS.md). Milestones M0 to M10 are built; the pilot (M11) is next. This file describes what exists. Companion to PROPOSAL.md (the "why"). This file is the "what to build."

Audience: the developer implementing milepost, and reviewers checking it against the proposal.

---

## 0. Decisions fixed by this spec

| Topic | Decision | Reason |
|---|---|---|
| Language | Python 3.12+ | Matches the team stack; MCP Python SDK; fastembed; tree-sitter bindings |
| Packaging | PyPI package `milepost`, managed with `uv` | Installable as a third-party tool; `uvx milepost` needs no prior install |
| License | Apache-2.0 | Permissive, patent grant, standard for dev tooling |
| CLI framework | Typer | Typed CLI, generates help text |
| Config | Pydantic v2 models loaded from `milepost.toml` | Validation with clear errors |
| Note format | Markdown + YAML frontmatter | Readable in PRs, diffable, merge-friendly |
| Index backend v1 | SQLite (stdlib `sqlite3`): FTS5 for keywords; vectors stored as float32 blobs and searched by exact cosine similarity in numpy | Zero infrastructure, and no loadable SQLite extension: many Python builds, including CI's, cannot load one (found when CI failed with `no attribute 'enable_load_extension'`). Exact search over a few thousand chunks takes milliseconds |
| Embeddings v1 | fastembed, model named in config | Local, no API key |
| Structure source v1 | Built-in scanner: Python `ast` + tree-sitter for TypeScript/JavaScript | No dependency on an external binary's API |
| Structure source v2 | Adapter for codebase-memory-mcp | Added once its query API is verified |
| Drafting | Claude Code writes the notes itself | Milepost never calls a model and holds no keys; `kb_draft_module` hands Claude the sources and `kb_update` saves the result |
| MCP server | `mcp` Python SDK (FastMCP), stdio transport | Standard transport for Claude Code |
| Claude Code integration | Plugin wrapper (see section 12) | Ships the MCP server, a usage skill, slash commands, and hooks |
| Plugin entry point | One user-facing command, `/kb-init`; everything else is called by it, by hooks, or by the agent (section 9.4) | Fewest required steps for a developer |
| Agent playbook | Scenario-to-tool steps in section 12.5 are normative; the skill and the CLAUDE.md snippet are derived from them | Agents and humans forget; the steps live in one place and enforcement does not rely on memory |
| Design principle | A note stores only what code cannot tell you: purpose, contracts, invariants, gotchas, intent. Anything derivable from code (symbols, line ranges, importers, tests) is computed live from the working tree by the tools in section 8.3 and is never stored | Stored copies of derivable facts go stale and add review load; computed ones cannot go stale |
| One note per module | No per-file or per-passage notes. Per-file detail comes from `kb_outline`, computed on demand | A model-written note per file multiplies review load and staleness; the outline gives the same pointers for free |
| Human visibility | An agent edit returns a note to `draft`; only `milepost review` sets `reviewed`. `milepost status` and `milepost report` show unreviewed churn and changed code that notes call risky (section 8.4) | Agents now change more code than people read; the notes are the cheapest thing a person can still read |
| Who writes notes | The coding agent, always: `kb_draft_module` returns a draft packet, the agent writes the body, `kb_update` saves it | A separate drafting model was removed: one path, no keys, no second provider |
| Note updates after a task | Always written by the agent that did the task, through `kb_update` | It has the change in context; a separate model would have to re-read it |

Revision to PROPOSAL.md section 6: a note stores no hash of its sources. A stored hash conflicted between concurrent pull requests that touched different files of one module, and re-hashing on merge would bless a note written against older code. Staleness is judged from git history instead (section 6).

### 0.1 Goals

1. **Cheaper, better agent context.** Before a task an agent should get, in a few small calls, the module that owns the work, the rules the code does not show, the exact symbols and line ranges to read, who depends on the file, which tests cover it, and whether the note can be trusted. Targets are in section 14 and are measured in the pilot, not assumed.
2. **Human visibility.** A developer who did not write a change should still be able to see what changed in each module, which notes no person has reviewed, and which changed code the notes call risky.

Both goals use the same artifact: short reviewed notes plus facts computed from git and source. Milepost does not detect bugs and does not verify that a note is true. A person reading the note is the control; milepost keeps notes short, keeps them honest about staleness, and points the reader at the right place (section 16).

---

## 1. Concepts

- **Module:** a named unit of the repo, declared in `milepost.toml`. Each module has exactly one note.
- **Note:** a markdown file `kb/modules/<id>.md` with YAML frontmatter and a prose body.
- **Source set:** the files a module covers, given as glob patterns relative to the repo root.
- **Staleness:** a note is stale when a file it covers changed after the note was last touched, judged from git history and uncommitted edits (section 6). Nothing about the code is stored in the note.
- **Index (L1):** the list of modules with a one-line purpose each. Not a file: rendered from the notes on demand (section 8.2).
- **Search index:** a derived, rebuildable local database. Never the source of truth.
- **Computed context:** facts derived from source and git at call time (outline, importers, related tests, churn). Never stored, so never stale.

There are no per-file or per-passage notes. Per-file detail (symbols, signatures, line ranges) is computed by `kb_outline` on demand (section 8.3).

---

## 2. Repository layout after init

```
<repo>/
  milepost.toml                  # config (committed)
  kb/
    modules/                  # one note per module (committed)
    .index/                   # search index (git-ignored)
  .gitattributes              # adds merge driver line for kb/**/*.md (committed)
  .github/workflows/milepost.yml # CI gate (committed)
```

`kb/.index/` is git-ignored. `init` appends it to `.gitignore`. (Earlier versions also ignored `kb/.progress.json` and `.env`; `uninstall` still removes the former.)

---

## 3. Configuration: `milepost.toml`

Full example is in `templates/milepost.toml.example`. Schema:

```toml
[project]
name = "example"                       # required, string
kb_dir = "kb"                          # default "kb"

[modules.<id>]                         # one table per module; id is [a-z0-9_-]+
sources = ["backend/app/services/**/*.py"]   # required, non-empty list of globs
related = ["ai"]                       # optional, ids of other modules
title = "Services"                     # optional, default = id
verify = ["pytest backend/app/tests/services"]   # optional; commands that check this module, returned by kb_module and kb_sync. Written by a person, never guessed by a model

[structure]
languages = ["python", "typescript"]   # default ["python"]
ignore = ["**/node_modules/**", "**/__pycache__/**", "**/.venv/**"]
roots = ["src", "app", "backend/app", "packages", "apps"]   # where module candidates live; used by init, scan, and coverage checks

[index]
backend = "sqlite"                     # only "sqlite" in v1
path = "kb/.index/index.sqlite"        # default shown
embedding_model = "BAAI/bge-small-en-v1.5"   # fastembed model name; config, not code
embedding_dim = 384                    # must match the model

[draft]
max_source_bytes = 200000              # per module; larger modules are read as outlines, see 9.3
exclude = ["**/.env*", "**/*secret*", "**/*.pem", "**/*.key", "**/credentials*"]
secret_scan_allow = []   # globs of files the secret scan would withhold but a person has checked

[check]
fail_on = "stale"                      # "stale" (default) or "none" (report only)
stale = "warn"                         # "warn" (default) or "fail": whether a stale note fails the check / pull request

[visibility]
agent_trailers = ["(?im)^Co-Authored-By:.*noreply@anthropic\\.com", "Generated with \\[?Claude Code"]   # regexes matched against commit messages to count agent-authored commits
churn_warn_lines = 1000                # warn UNREVIEWED_CHURN above this many changed lines since the last review; a placeholder to tune in the pilot
```

Validation rules (fail fast, exit code 2):
- Module ids are unique and match `^[a-z0-9][a-z0-9_-]*$`.
- Every `sources` list is non-empty and every glob is relative (no leading `/`, no `..`).
- Every entry in `related` names a declared module.
- `index.backend` is `sqlite`.
- `embedding_dim` is a positive integer.
- Every `structure.roots` entry is relative (no leading `/`, no `..`).
- `verify` is a list of strings.
- `churn_warn_lines` is a non-negative integer; every `agent_trailers` entry is a valid regular expression.
- `check.stale` is `warn` or `fail`.

Milepost stores no credentials and reads no model settings. Configs written by earlier versions may still contain `mode = "agent"` and `provider_model` under `[draft]`; both are accepted and ignored. Both are ignored, including `mode = "model"`, so an upgrade never locks a repository out of its commands; `milepost doctor` warns and says to delete the line.


---

## 4. Note format

### 4.1 Frontmatter

```yaml
---
kb_schema: 1                       # required, integer, currently 1
id: module/services                # required; "module/<module-id>", matching the file name
title: Services                    # required, one line
status: draft                      # required; draft | reviewed
sources:                           # required; mirrors the module's globs in milepost.toml
  - backend/app/services/**/*.py
related: [ai, data]                # optional
written_by: agent                  # required; agent | human | draft-command (the last only in notes from older versions)
written_at: 2026-10-07T09:12:00Z   # required, UTC ISO-8601
reviewed_by: Jane Doe <jane@example.com>   # optional; set only by `milepost review`
reviewed_at: 2026-10-08T14:00:00Z  # optional; set only by `milepost review`
---
```

Older notes may carry `level` and `source_hash`. They are ignored when reading and dropped when milepost rewrites the note.

Status rules, which the visibility features depend on: `milepost review` is the only thing that sets `status: reviewed` (it also writes `reviewed_by` and `reviewed_at` from the git identity). Every `kb_update`, and every draft, sets `status: draft` and removes `reviewed_by` and `reviewed_at`. So an agent's edit to a reviewed note shows up in the pull request as a visible flip from `reviewed` to `draft`.

### 4.2 Body

Free markdown. Recommended sections for a module note (not enforced except that the body must be non-empty):

```
## Purpose          one or two sentences; the first sentence becomes the module's line in the index
## Entry points     the few places to start reading, with paths
## File map         one line per file, or per folder for large modules, saying what it does
## Owned data
## Invariants       each bullet cites the file (and symbol) in backticks that enforces it
## Gotchas          same: cite the file in backticks
## Related modules
```

Keep a note under about 600 words. Cite paths in backticks (`` `routes/auth.py` ``, `` `routes/auth.py::login` ``): `milepost report` and `kb_sync` use those citations to point reviewers and agents at the right bullet when that file changes (section 8.3). Test commands do not go in the note; they are the `verify` list in `milepost.toml`.

### 4.3 Validation

`milepost check` rejects a note when:
- frontmatter is missing or not valid YAML;
- a required key is missing;
- `kb_schema` is not `1`;
- `status` is not `draft` or `reviewed`;
- `id` does not match the file path (`kb/modules/services.md` must have `id: module/services`).

---

## 5. Content hash (a read receipt, never stored)

`kb_module` returns `source_hash_now`, a digest of the module's source files as they are on disk. `kb_update` must be given it back as `read_hash`; if the sources changed in between, the write is rejected with `STALE_READ`. That proves the agent fetched the note after the last source change. The hash is computed when needed and is never written to a note, so it cannot conflict between branches. It is defined precisely so that two machines compute the same value:

1. Expand each glob in the module's `sources` against the repo root with `wcmatch.glob.glob(pattern, root_dir=repo_root, flags=GLOBSTAR | DOTGLOB | FOLLOW)`. Keep regular files only. De-duplicate. Then drop every path matched by any `structure.ignore` pattern using `wcmatch.glob.globmatch` with the same flags. Exclude nothing else (dotfiles are included).
2. Sort the resulting repo-relative POSIX paths lexicographically.
3. For each path, read the bytes. Normalize line endings: replace `\r\n` with `\n`, then replace lone `\r` with `\n` (skipped for files containing a NUL byte). Do not strip whitespace.
4. `file_digest = sha256(normalized_bytes).hexdigest()`.
5. Manifest text: one line per file, `<path>\t<file_digest>\n`.
6. Result: `"sha256:" + sha256(manifest_bytes).hexdigest()`. With zero matched files, the digest of the empty string.

---

## 6. Staleness and the check command

### 6.1 How staleness is judged

Git is the source of truth; nothing is stored in the note. For each module whose note file exists:

1. If the note and a covered file both have uncommitted edits, the note is **stale** when the code was saved after the note (file modification time), otherwise fresh.
2. If only the note has uncommitted edits, it is **fresh** (someone just touched it).
3. If only covered files (the module's globs, minus `structure.ignore` and the kb folder) have uncommitted changes, it is **stale**.
4. Otherwise let *N* be the latest commit that touched the note. The note is **stale** if some commit that touched a covered file (deleted files count, because the pathspec is the glob) is not reachable from *N*, that is, if `git log N..HEAD -- <covered files>` is not empty. This also catches code that landed from another branch after the note's last update, whatever its commit date.

"Touched" means any edit to the note, including an unchanged body re-saved by `kb_update`. This is an approximation of "the note was written against this code": it cannot tell whether the note's author read the new code. Review is what vouches for the prose. Two consequences are deliberate: a pull request that changes code and the note together is fresh, and two pull requests that change different files of one module cannot conflict over a stored hash because there is none.

Staleness cannot be judged outside a git repository or in a shallow clone (too little history): `check` then reports `STALENESS_UNAVAILABLE` and judges nothing, and the MCP tools report no staleness. CI should fetch full history (the generated workflow does). A project that lives in a subdirectory of a larger git repository works: paths are taken relative to the project.

### 6.2 The check

`milepost check` performs, in order:
1. Load and validate config (section 3).
2. Validate every note under `kb/modules` (section 4.3).
3. Staleness (6.1). A stale note is a `STALE_NOTE` finding, a **warning** by default and a failure when `[check] stale = "fail"`. Also warn `EMPTY_SOURCE_SET` when a note's sources match no files.
4. For each declared module with no note, emit a warning (not a failure).
5. If a `kb/INDEX.md` left over from an older version exists, emit a warning `INDEX_OBSOLETE` (the index is no longer stored).
6. Coverage: for each directory that is a direct child of a `structure.roots` entry and contains at least one non-ignored file in a configured language, emit a warning `UNCOVERED_DIR` when no module's `sources` match any file in it.
7. Citations: every path cited in backticks in Entry points, File map, Invariants or Gotchas must match a file in the repository (equal, or a suffix after `/`); a cited directory (trailing `/`) must exist; and for a cited `file::symbol` in a uniquely matched file, the symbol's last name must appear in the file text. The test is deliberately lenient so it flags only what is clearly absent. A backtick span is treated as a path only if it ends in `/`, has an extension, or (without a `/`) ends in a known file extension, so routes like `api/users`, phrases like `and/or` and symbols like `Class.method` are ignored; a leading `./` and a `:42` line suffix are dropped. Otherwise emit a warning `CITATION_BROKEN`. At most 200 citations per note are checked, and an unreadable file is skipped, never an error. This catches invented details; it does not prove a true citation supports its claim.
8. Unreviewed churn: for each note that has been reviewed at least once, when the lines changed in its source files since its last review (section 8.4) exceed `visibility.churn_warn_lines`, emit a warning `UNREVIEWED_CHURN`. Never a failure, and never emitted for a note no person has reviewed yet.

Output: human text by default; `--format json` emits a list of findings `{severity, code, path, message}`.

Exit codes:
- `0`: no failures.
- `1`: at least one failure (an invalid note; a stale note only when `[check] stale = "fail"`).
- `2`: config or usage error.

### 6.3 CI mode

`milepost check --ci --base <ref>` judges a pull request by what it changes, from the diff alone:
- **Stale note:** the range edits a file a note covers and does not touch that note. That is a `STALE_NOTE` finding (a failure only when `[check] stale = "fail"`). If the range touches both, nothing is reported, whatever the order of the commits inside it.
- A note that is stale by 6.1 but whose covered files the range does not touch is old debt: a warning.
- `UNCOVERED_DIR` fails when the directory gained its first source file in the range.
- Waivers: a commit may carry the trailer `KB-Waive: <note-id> <reason>` (or `KB-Waive: dir:<path> <reason>`). In CI mode it downgrades that failing finding to a warning. A waiver without a reason is an error (exit 2).

A declared module with no note still only warns, locally and in CI.

---

## 7. Index

### 7.1 Contents

Chunks are created from:
- each L1 entry (one chunk per module line);
- each module note split on `##` headings (chunk = heading + body, max 2,000 characters; longer sections split on paragraph boundaries).

Each chunk stores: `chunk_id`, `note_id`, `heading`, `text`, `embedding`.

### 7.2 Storage (SQLite)

```sql
CREATE TABLE notes (note_id TEXT PRIMARY KEY, level TEXT, status TEXT, source_hash TEXT, content_sha TEXT, indexed_at TEXT);   -- level is 'L1' for the index row and 'L2' for module notes; source_hash is unused and empty
CREATE TABLE chunks (chunk_id INTEGER PRIMARY KEY, note_id TEXT, heading TEXT, text TEXT);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, heading);   -- rowid = chunk_id, kept in step by the store
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);          -- embedding_model, embedding_dim
CREATE TABLE chunk_vectors (chunk_id INTEGER PRIMARY KEY, embedding BLOB NOT NULL);   -- float32 x dim from config
```

### 7.3 Rebuild rules

- `milepost index` is incremental: a note is re-chunked and re-embedded only when its `content_sha` (sha256 of the file bytes) changed.
- `milepost index --rebuild` drops and recreates all tables.
- A schema or model change (different `embedding_model` or `embedding_dim`) forces `--rebuild`; the stored model name is kept in a `meta` table and compared on every run.
- Vectors are optional (the `search` extra). The `meta` table records `vectors` as `True`, `False` (keyword only) or `mixed` (some notes were indexed while the extra was missing). An index with vectors is never wiped because one process lacks the extra; it is rebuilt with vectors automatically when the extra is present and the state is `False` or `mixed`. A keyword-only index is never queried with an embedded query.
- The index never affects `milepost check`. Check reads files only.

### 7.4 Search

`milepost search <query> [--k 5]`: hybrid. Run FTS5 BM25 and vector KNN (k = 20 each), merge with reciprocal rank fusion (k = 60), return the top `k`. Each result: `note_id`, `heading`, `score`, `snippet` (max 300 characters), `status`.

The vector half is an exact scan: it loads the candidate vectors, computes cosine similarity against the query, and keeps the top results. That is milliseconds at the intended scale (a few hundred notes, a few thousand chunks). It is not meant for hundreds of thousands of chunks; a larger deployment would use the Postgres backend (pgvector) deferred in section 16.

The keyword query drops common English filler words (a fixed list in the store) and ORs the remaining terms, so that words like "how" and "the" do not outrank real matches; the vector search sees the whole query. Without this, a query whose keyword hits were all filler pushed the right note out of the fused top results (found with the 20-note fixture KB).

---

## 8. Commands

All commands accept `--repo <path>` (default: nearest ancestor with `milepost.toml`). All print to stdout; diagnostics go to stderr. `--json` is available on every command that prints results.

| Command | Purpose | Notes |
|---|---|---|
| `milepost init [--dry-run] [--modules ID,...] [--yes] [--force-config] [--no-hooks]` | Scaffold, declare modules, install hooks, build the index, and list the modules Claude should write notes for (section 9) | Never overwrites existing files; `--modules` and `--yes` are what the plugin's `/kb-init` uses |
| `milepost check [--ci --base REF] [--format text\|json]` | Validate and detect staleness (section 6) | Exit codes in section 6 |
| `milepost index [--rebuild]` | Build or update the local search index (section 7) | Safe to run from git hooks |
| `milepost overview` | Print the L1 module index, rendered from the notes (section 8.2) | Read-only |
| `milepost review <note-id>` | Set `status: reviewed` after human sign-off | Records `reviewed_by` and `reviewed_at` from the git identity (exit 3 if it is not set); refuses a stale note |
| `milepost outline <path> [--json]` | Symbols, signatures and line ranges of one file, computed now | Section 8.3 |
| `milepost impact <path> [--json]` | Files that import this file and the tests likely to cover it, computed now | Section 8.3 |
| `milepost sync [--base REF] [--json]` | What changed and which notes to update, and how | Section 8.3; read-only |
| `milepost status [--json]` | Per module: review state and unreviewed churn | Section 8.4; read-only |
| `milepost report --base REF [--format markdown\|json]` | Review aid for a change range | Section 8.4; read-only, always exits 0 |
| `milepost search <query> [--k N]` | Hybrid search | Section 7.4 |
| `milepost hooks install \| uninstall` | Manage git hooks and merge driver config | Section 10 |
| `milepost merge-driver %O %A %B %P` | Invoked by git for `kb/**/*.md` | Section 10.3 |
| `milepost serve` | Run the MCP server on stdio | Section 11 |
| `milepost doctor` | Print environment: Python, git, SQLite FTS5 available, whether the search extra is installed, whether `milepost.toml` loads, and whether the git hooks are current | Read-only; exit 3 when git or FTS5 is missing or the config is invalid |
| `milepost scan [--json]` | List candidate modules under `structure.roots` that no declared module covers (same scan as init step 3) | Read-only; never edits config |
| `milepost hook session-start` | Print the index and a reminder as session context | Used by the plugin hook, section 12.4; always exits 0 |
| `milepost hook post-edit` | Read Claude Code hook JSON on stdin, find the edited path, print the notes that cover it | Used by the plugin hook, section 12.4; always exits 0 |
| `milepost hook stop` | Run `milepost check`, print findings in hook format | Used by the plugin hook, section 12.4 |

### 8.1 Exit codes (all commands)

`0` success, `1` a check or operation found failures, `2` usage or config error, `3` environment error (missing dependency, unreadable repo), `4` LLM provider error.

### 8.2 The L1 index (rendered, never stored)

Deterministic. It used to be a committed file; as a stored file it drifted whenever a status or Purpose changed and conflicted whenever two pull requests touched different modules, so it is now rendered from the notes on demand. Format:

```markdown
# Codebase index

| Module | Purpose | Status | Note |
|---|---|---|---|
| services | Business logic behind the API routes; owns billing and enrollment rules. | reviewed | kb/modules/services.md |
```

Rows are sorted by module id. The purpose is the first sentence of the note's `## Purpose` section, whitespace collapsed and cut to 160 characters; it is `(no note yet)` when the note is missing and `(no Purpose section)` when it has none. Renders from notes only; no timestamps. 

### 8.3 Computed context: `outline`, `impact`, `sync`

These read the working tree and git at call time. Nothing they return is stored in `kb/` or the index, so none of it can go stale.

**`outline <path>`.** Parses one file and lists its symbols in line order. Python uses the stdlib `ast`; TypeScript and JavaScript use tree-sitter. Each symbol has: `name` (qualified for methods, `Class.method`), `kind` (`function`, `class`, `method`, `interface`, `type`, `const`), `signature` (the first line of the definition), `doc` (first docstring or leading comment line, at most 120 characters, may be empty), `start_line`, `end_line`. At most 200 symbols are returned; beyond that `truncated` is true. The path must be inside the repository. An unsupported extension is a usage error (exit 2, `INVALID_INPUT` in MCP) whose message includes the file's line count, so the caller knows whether to read it whole.

**`impact <path>`.** Uses the structure scanners (section 15) over source files in the configured languages, excluding `structure.ignore`, to find internal imports that target `<path>`. The file list comes from git (tracked files plus untracked files that are not ignored), so virtualenvs, build output and agent worktrees that git ignores are never read; outside a git repository it falls back to globbing. Only files whose text contains the target's module name are parsed. Measured on a real repository of about 2,000 tracked files: under 1 second per call, where listing by glob took about 50 seconds because it also read agent worktree copies. Returns: `importers` (files importing it); `tests` (importers that look like tests, plus files elsewhere whose name contains the target's stem and that look like tests, each marked `via: import` or `via: name`); `modules` (declared modules whose sources cover the path, with their `verify` commands); `notes` (covering note ids). A file looks like a test when its path contains `tests/`, `test/` or `__tests__/`, or its name matches `test_*.py`, `*_test.py`, `*.test.*` or `*.spec.*`. Each list is capped at 50 with `truncated` set. This is a static import graph: dynamic imports, string-based plugin loading and framework wiring are not seen, and the response says so.

**`sync [--base REF]`.** Lists files changed in the working tree against `HEAD` (staged, unstaged and untracked), or against `--base REF...HEAD` when given. A rename counts as one delete plus one add. For each changed file outside `kb/` it returns the declared modules and notes that cover it (a deleted path is matched against the module globs as a string), each note's `stale` flag and `source_hash_now`, and the routes below. It also returns the `verify` commands of every affected module and a `next_steps` list. Routing is rule-based and deterministic; no model is involved:

| Change | What to update |
|---|---|
| File modified in a module | The module note: re-read the file, edit Purpose, File map, Invariants or Gotchas if the change affects them, otherwise call `kb_update` with the unchanged body to confirm it still holds (that touches the note, so it is no longer stale) |
| File added in a module | The note's File map (add a line); Entry points if it is a new starting point |
| File deleted or renamed | The note's File map (remove or rename the line) |
| Path covered by no module | `UNCOVERED_DIR` guidance: declare a module (playbook 8) or ask the user |
| A backticked path cited in an Invariants or Gotchas bullet is among the changed files | Name that bullet and note id: "confirm this still holds" |
| File under `kb/` | Nothing |

Citation matching: a cited path matches a changed file when it equals the file's path or is a suffix of it after a `/`, and exactly one file in the module's source set has that suffix. Ambiguous citations are skipped, not guessed.

### 8.4 Human visibility: `status`, `report`

Both are derived from git and the notes, are read-only, and never fail a build. They exist so a person who did not write a change can see where attention is needed.

**Review baseline.** For a note, the baseline is the most recent commit in the current history that recorded a review: one that added or removed a `reviewed_at` line and left the note `status: reviewed` (notes reviewed by hand, without `reviewed_at`, fall back to the latest commit that touched the status line). A typo fix on an already-reviewed note does not reset it. This survives squash merges and rebases, unlike a stored commit id. No baseline means no person has reviewed the note. Churn counts every file in the module's source globs that changed since the baseline, including files deleted or moved away since.

**`status`.** One row per declared module: note status, `reviewed_by` and `reviewed_at` from the frontmatter, `commits_since` and `lines_changed_since` (added plus deleted lines in the module's source files since the baseline, from `git diff --numstat`), and `agent_commits_since` (commits since the baseline that touch those files and whose message matches any `visibility.agent_trailers` regex). A module with no baseline shows `never reviewed`. Rows are ordered by `lines_changed_since`, largest first, never-reviewed modules first. The agent count is a heuristic: it only sees commits that carry a trailer or phrase the team configured.

**`report --base REF`.** For the range `REF...HEAD`, prints markdown (or JSON) with these sections, each omitted when empty and the whole report saying "nothing needs attention" when all are:
1. **Notes changed:** each note touched in the range, with its status before and after, so a flip from `reviewed` to `draft` is visible.
2. **Stale notes covering changed files:** the same findings `check --ci` would fail on.
3. **Changed files no module covers.**
4. **Changed code the notes call risky:** each Invariants or Gotchas bullet whose cited path (matching rule in 8.3) is among the changed files, quoted with the note id.
5. **Unreviewed churn:** modules over `visibility.churn_warn_lines`.

The report reads the "before" status from the fork point (`git merge-base`), lists only changed files under `structure.roots` in a configured language, and prints "Report unavailable: ..." and exits 0 when git cannot answer (for example an unknown base ref), so it never fails a pull request.

The CI workflow writes this report to the job summary (`$GITHUB_STEP_SUMMARY`), which needs no extra permission. Posting it as a pull request comment needs `pull-requests: write` and is documented as optional in USAGE.md.

**Ownership.** `templates/CODEOWNERS.snippet` shows a line that makes a named person or team required reviewer for `kb/`. `init` does not write it because milepost cannot know the team names. Together with the status rules in 4.1, this means a note change by an agent needs a person's approval.

---

## 9. Initialization (`milepost init`)

### 9.1 Steps

1. **Preflight:** confirm a git repository exists. Refuse if `milepost.toml` exists unless `--force-config` or `--modules` is given (never overwrites notes).
2. **Scaffold:** write `milepost.toml` from the template with the detected Python and TypeScript roots filled in as commented suggestions; create `kb/`; append ignore lines (`kb/.index/`, `kb/.progress.json`, `.env`) to `.gitignore`; write `.gitattributes` line if absent; write `.github/workflows/milepost.yml` from `milepost/resources/ci-kb-check.yml` if absent, with the installed milepost version pinned.
3. **Structure scan:** build the module proposal. Top-level directories under the `structure.roots` entries become candidate modules. Without `--modules`, candidates are written as commented entries; the user uncomments and confirms. The scan never activates a module on its own. With `--modules a,b`, the named candidates are written as active `[modules.<id>]` tables; naming an id that is not a current candidate is a usage error (exit 2). The explicit flag is the confirmation.
4. **Hooks:** if `--no-hooks` is absent, run `milepost hooks install`.
5. **Draft:** skipped. `init` lists the declared modules that have no note; Claude writes them through `kb_draft_module` and `kb_update`. With `--dry-run` it prints the files Claude would read, the module count and the estimated tokens (file bytes / 4 as a rough estimate).
6. **Index:** `milepost index`.
7. **Report:** print the CLAUDE.md snippet location, the CI template location, and the next command (`milepost review <id>` per draft).

### 9.2 Idempotency

Re-running `init` creates only what is missing. Existing `kb/modules/*.md` files are not modified. Existing `milepost.toml` is not modified unless `--force-config`, with one exception: `--modules` appends `[modules.<id>]` tables for modules not yet declared and changes nothing else in the file. That is how a module is added after the first run.

`--yes` skips confirmation prompts. Without it, in an interactive shell, `init` prints the module list, the files Claude would read for drafting, and the token estimate, and asks once.

### 9.3 Drafting

**Drafting.** Milepost never calls a model and needs no key: `milepost init` scaffolds, declares modules and builds the index, and Claude drafts through `kb_draft_module`. That tool returns a *draft packet* instead of writing a note: the drafting prompt, the collected sources (after `draft.exclude`, the size budget and the secret scan), and an instruction to write the body and submit it with `kb_update`. `kb_update` may create a missing note for a declared module, and always writes `status: draft`. `draft.exclude` and the secret scan protect only the packet; the agent can still read any file with its own tools, so they are not a guarantee. Updates after a task are written by the agent too (section 0).

- Input: the module's source files, concatenated with headers `=== path ===`, after applying `draft.exclude`. If the total exceeds `max_source_bytes`, include the structure summary (imports, top-level symbols) for every file and full text only for the first N files that fit, and state the truncation in the note body.
- Prompt: stored in `milepost/prompts/draft_l2.md` (not inline in code). It tells the agent to write only what is verifiable from the provided code, to mark uncertainty explicitly, to avoid describing behavior not present in the input, to cite file paths in backticks, to include a File map, and to stay short.
- Output: frontmatter is written by milepost, never by the agent; the body comes from the agent through `kb_update`, which validates it.
- Seed documents (`--seed-docs`): included in the prompt with the label "documentation, not verified against code." Notes derived from them must say so in the body.

### 9.4 Plugin entry point: `/kb-init`

`/kb-init` is the only slash command the plugin ships. A developer runs it once; every other step is called from it, by hooks, or by the agent. `plugin/commands/kb-init.md` instructs the agent to:

1. Run `milepost doctor --json`. Read the output and fix or report anything marked `fail`.
2. Run `milepost scan --json` and `milepost init --dry-run --modules <all candidates>`. Show the candidate modules, the files that would be sent, and the estimated tokens, and ask once which modules to keep.
3. Run `milepost init --yes --modules <confirmed ids>`: scaffold, declare the modules, install hooks and the merge driver, write the CI workflow, draft the L2 notes, and build the index.
4. Report the one step that needs a person: read each draft under `kb/modules/`, run `milepost review <id>` for each one that is right, then commit `milepost.toml`, `kb/`, `.gitattributes`, and `.github/workflows/milepost.yml`.

The command does not print the CLAUDE.md snippet, because the plugin's skill and hooks carry the same rules. Re-running is safe (section 9.2) and is how modules are added later: the scan lists only undeclared candidates. `milepost check` is not a slash command; agents use `kb_check` and the `Stop` hook, and developers run the CLI.

### 9.5 Security

- Files matching `draft.exclude` are never read for drafting.
- Before handing sources to Claude, milepost scans them for common secret patterns (AWS key ids, private key headers, `password=`/`token=` assignments with long values). A match withholds that one file from the packet (the rest of the module is still drafted) and the note states which files were withheld, by path and never by value. If every file is withheld, drafting stops with a usage error. A person who has checked a file lists it in `draft.secret_scan_allow` (globs) to include it.
- `--dry-run` lists every file Claude would read, so a reviewer can check the set first.

---

## 10. Git integration

### 10.1 Hooks

Installed into `.git/hooks/` by `milepost hooks install`. Each hook is a three-line shell script that calls `milepost` and exits with the command's status unless noted.

| Hook | Command | Failure behavior |
|---|---|---|
| `post-merge` | `milepost index` | Non-blocking: errors print a warning, exit 0 |
| `post-checkout` | `milepost index` | Non-blocking, as above |
| `pre-commit` | `milepost check --no-churn` | Blocking on `fail_on = "stale"`. The churn warning needs several git calls per module (about 7 seconds extra on 5,000 files and 20 modules), so the hook skips it; CI and `report` still show it |

If a hook directory is managed by another tool (for example the `pre-commit` framework), `milepost hooks install` prints the snippet to add to that tool's config instead of writing to `.git/hooks`.

Hooks installed by milepost are marked with a comment line `# managed-by: milepost`. `uninstall` removes only files carrying that marker, and unsets the merge driver config. Every hook first checks that `milepost` is on the PATH and exits 0 with a warning if it is not, so a missing install never blocks git. If `core.hooksPath` is set, or any of the three hook files exists without the marker, `hooks install` writes nothing and prints the snippet. `milepost init` runs `hooks install` unless `--no-hooks` is given.

`pre-commit` runs the whole-repository `milepost check`, so a note that was already stale blocks every commit until fixed. That is the specified behavior; a developer who needs to commit past it uses `git commit --no-verify`, and CI still judges the pull request by what it changes (section 6).

### 10.2 CI workflow

`milepost/resources/ci-kb-check.yml` runs on `pull_request` and on `push` to `main`:
- `pull_request`: `milepost check --ci --base ${{ github.base_ref }}`. Fails the job on exit 1.
- `push` to `main`: `milepost index` writes the shared index if a shared backend is configured; otherwise a no-op.
- `pull_request` also runs `milepost report --base ${{ github.base_ref }}` and appends it to `$GITHUB_STEP_SUMMARY`. The step never fails the job (section 8.4).

The workflow installs milepost with `uv tool install milepost==<pinned version>`. The version is pinned in the workflow, not `latest`.

### 10.3 Merge driver

`.gitattributes`: `kb/**/*.md merge=milepost`

Git config (set by `hooks install`): `merge.milepost.driver = milepost merge-driver %O %A %B %P`

Behavior of `milepost merge-driver`:
1. Run `git merge-file` on the bodies (text after the frontmatter) with the base, ours, and theirs versions. Body conflicts are written as standard conflict markers and the driver exits non-zero, which leaves the file conflicted for a human.
2. For frontmatter, take each key from ours or theirs when only one side changed it. When both changed a key to different values, keep the value from ours (for `status`, `draft`).
3. A review only counts for the prose the reviewer read. If the merged status is `reviewed` but the merged body is not exactly the body of the side that holds that review (and not the unchanged base body), the driver sets `status: draft` and removes `reviewed_by` and `reviewed_at`. An edit by one side always wins over a review by the other: a status that is `draft` on one side and unchanged on the other becomes `draft`.
4. Write the result to `%A`.
5. A file with no frontmatter is merged as plain text.

Result: notes store no hash, so two pull requests that change different files (or different paragraphs) of one module merge cleanly. A merge never silently turns unreviewed prose into a `reviewed` note.

---

## 11. MCP server

Started by `milepost serve` over stdio. Built with FastMCP. Each tool returns text (markdown) and a structured object with the same data. Responses are bounded: a single note returned at most 20,000 characters; search returns at most 10 results.

Every response is also size-bounded by the per-tool caps in section 14. Every response also carries `next_steps`: a list of short instructions computed deterministically from repository state (never by a model), for example "3 notes cover this path; call kb_update on each after you change it". The rules for each tool are in section 12.5.

| Tool | Input | Output |
|---|---|---|
| `kb_overview` | none | L1 index markdown, plus a count of stale notes and the current branch name |
| `kb_module` | `id: str` | Note frontmatter and body, `stale` and why, `source_hash_now` (content hash of the sources as they are on disk, section 5), the module's `verify` commands, plus `related` note summaries (id, title, status) |
| `kb_file` | `path: str` | The note(s) whose sources match the path, each with `stale` and `source_hash_now` |
| `kb_search` | `query: str`, `limit: int = 5` | Hybrid search results (section 7.4) |
| `kb_update` | `id: str` (`module/<id>`), `body: str`, `read_hash: str` | Writes the note with `status: draft` (and removes `reviewed_by` and `reviewed_at`), mirrors `sources` from `milepost.toml`, returns `milepost check` findings for that note. Writing counts as touching the note, so it is no longer stale. It cannot set `reviewed`; only `milepost review` can |
| `kb_check` | none | Same findings as the CLI, including `UNCOVERED_DIR` warnings |
| `kb_draft_module` | `id: str` | Returns a draft packet for a module already declared in `milepost.toml`; writes nothing; section 11.3 |
| `kb_outline` | `path: str` | Symbols, signatures and line ranges of the file, computed now (section 8.3) |
| `kb_impact` | `path: str` | Importers, likely tests, covering modules and notes (section 8.3) |
| `kb_sync` | `base: str \| None` | Changed files, the notes to update and how, and the `verify` commands (section 8.3) |

### 11.1 Write discipline

`kb_update` is only safe if the agent has read the current source before writing. To enforce this, `kb_module` returns `source_hash_now` (the content hash of section 5) and `kb_update` requires that value back as `read_hash`. If it differs from the hash of the working tree at write time, the source changed after the agent read it and the write is rejected with `STALE_READ`. The agent must read again and retry.

This proves the agent fetched the note after the last source change; it does not prove the agent understood the code. Reading source files directly is still required by the playbook (section 12.5).

A `kb_update` whose body is identical to the current body is allowed. It refreshes `written_at`, counts as touching the note (so it is no longer stale), and is how an agent records "re-read the new source, the note is still accurate".

`kb_update` rejects:
- an id that is not `module/<module-id>`, or a module not declared in `milepost.toml` (`INVALID_INPUT`, `NOT_FOUND`);
- writes to a note that does not exist, unless the module is declared in `milepost.toml`;
- a missing or mismatched `read_hash` (`STALE_READ`);
- bodies longer than 20,000 characters, or that look like they contain a credential;
- an existing file that is not a valid note (it is never overwritten).

It writes only the body, `status` (always `draft`), `written_by`, `written_at` and `sources`/`title`/`related` as mirrored from `milepost.toml`, and removes `reviewed_by` and `reviewed_at`.

### 11.2 Errors

Tool errors return a structured error `{code, message}` with codes `NOT_FOUND`, `INVALID_INPUT`, `CONFLICT`, `STALE_READ`, `ENVIRONMENT`. Stack traces are logged to stderr only.

### 11.3 `kb_draft_module`

Lets an agent create the note for a new module in the same change as the code, without a CLI round trip.

- Precondition: the module id is declared in `milepost.toml`. The tool never edits config; the agent adds the `[modules.<id>]` entry as an ordinary file edit first. An undeclared id returns `NOT_FOUND` with `next_steps` naming the config entry to add.
- Refuses with `CONFLICT` if a note for the module already exists. Redrafting is a human action.
- `draft.exclude`, the secret scan and the size budget all apply to the packet.
- It returns the draft packet described in section 9.3 and calls no model.
- `next_steps` always includes: "ask a human to run `milepost review <id>` after reading the note".

---

## 12. Claude Code plugin

### 12.1 Feasibility and language

Yes. Claude Code plugins can bundle an MCP server, skills, and slash commands. The MCP server runs as a separate process over stdio, so the server language is independent of Claude Code. The plugin manifest and skills are JSON and Markdown.

Python is the right language. The MCP server is the only code the plugin runs; it needs a Python runtime, and the Python ecosystem already provides the SDK, and fastembed. A TypeScript rewrite would add a second toolchain for no gain. Users run the server with `uvx milepost serve`, so they do not install anything globally first.

The plugin layout (`.claude-plugin/plugin.json`, `.mcp.json`, `skills/`, `commands/`, `hooks/hooks.json`, with `${CLAUDE_PLUGIN_ROOT}` in paths) was verified against the Claude Code plugin documentation in October 2026, and `claude plugin validate ./plugin` passes.

### 12.2 Plugin contents

Shipped from `plugin/` in the milepost repository:

```
plugin/
  .claude-plugin/plugin.json      # name, version, description
  .mcp.json                       # starts the server. MVP: `uv run --project ${CLAUDE_PLUGIN_ROOT}/.. milepost serve` (loaded in place with --plugin-dir). Release: `uvx milepost==<version> serve`
  skills/kb-usage/SKILL.md        # read and write discipline for agents
  commands/kb-init.md             # /kb-init, the only slash command; flow in section 9.4
  hooks/hooks.json                # SessionStart, PostToolUse and Stop hooks, section 12.4
```

The skill text is in `plugin/skills/kb-usage/SKILL.md`. It is derived from the playbook in section 12.5 and must name only tools that exist in the MCP server (section 11).

### 12.3 Distribution

- Package on PyPI as `milepost`. The plugin's MCP command pins the same version.
- The plugin folder is published as a Claude Code plugin marketplace entry or installed from the repository, following the Claude Code plugin docs at the time of release.

### 12.4 Hooks

Hooks are run by the Claude Code harness, not by the model, so they work when the agent forgets. Shipped in `plugin/hooks/hooks.json`:

| Hook | Matcher | Command | Behavior |
|---|---|---|---|
| `PostToolUse` | `Edit`, `Write`, `MultiEdit`, `NotebookEdit` | `uvx milepost==<version> hook post-edit` (MVP: `uv run --project ${CLAUDE_PLUGIN_ROOT}/.. milepost hook post-edit`) | Reads the hook JSON on stdin, takes `tool_input.file_path` (or `notebook_path`), and returns as added context the notes covering that path (id, status, stale flag) plus the instruction "update each covering note with `kb_update` before finishing". Prints nothing for paths under `kb/` and for paths no note covers, except one line naming `UNCOVERED_DIR` when the path is in an uncovered directory. Never blocks; exits 0. |
| `SessionStart` | none | `uvx milepost==<version> hook session-start` | Adds as context the L1 index (cut to 3,000 characters), the count of stale and draft notes, and a three-line reminder of playbook scenario 1. This puts orientation in front of the agent without a tool call. Prints nothing when the repository has no `kb/`. Never blocks; exits 0. |
| `Stop` | none | `uvx milepost==<version> hook stop` | Runs `milepost check`, but blocks only on a `STALE_NOTE` whose sources match a file changed in this piece of work (the working tree against HEAD plus the latest commit, ignoring `structure.ignore`). Other failures and old debt are left to `check`, `pre-commit` and CI. The block reason lists the findings and the playbook step to follow. Blocks at most once per stop sequence: if the hook input says a stop hook is already active (`stop_hook_active`), it exits 0, so a failure it cannot fix does not loop forever. |

All three hooks fail open: if `milepost` is not installed or errors, they exit 0 with a warning on stderr. Enforcement that cannot be bypassed stays with `pre-commit` and CI (section 10).

The hook JSON field names, matcher syntax, `stop_hook_active`, the `hookSpecificOutput.additionalContext` output and the `decision: "block"` output were verified against the Claude Code hooks documentation in October 2026.

### 12.5 Agent playbook

This table is normative. The skill (`plugin/skills/kb-usage/SKILL.md`) and the CLAUDE.md snippet are written from it, and a test (TASKS M10) checks that every tool the skill names exists. Calls are in order.

| # | Scenario | Agent calls | If it cannot proceed |
|---|---|---|---|
| 1 | Start a task | `kb_overview`; `kb_module` for the owning module (read Invariants and Gotchas, note the `verify` commands); `kb_outline` for each file to read, then read only the line ranges you need; `kb_impact` for each file to change; `kb_search` if the module is unclear | No `kb/` folder: skip the playbook |
| 2 | Note is `draft` | Use it; verify its claims in source; tell the user a draft note was relied on | none |
| 3 | Note is stale | Read current source; `kb_update` with corrected body and `read_hash` from the last `kb_module` or `kb_file` | `STALE_READ`: call `kb_module` or `kb_file` again and retry |
| 4 | Change an existing file | Read the relevant lines; change it; run the module's `verify` commands; `kb_sync`; `kb_update` on every note it lists; `kb_check` | A finding the agent cannot fix: report it, do not waive |
| 5 | Add a file to an existing module | `kb_module`; read the new source; `kb_sync`; `kb_update` on the note (File map, and Entry points if it is a new starting point); `kb_check` | none |
| 6 | Rename or delete a file | `kb_impact` on the old path before the change (who imports it); after the change, `kb_sync` and `kb_update` on each covering note; `kb_check` | none |
| 7 | Learned a gotcha or invariant | `kb_update` on the note (Gotchas or Invariants, citing the file in backticks) after reading the source it refers to | none |
| 8 | New module | Add `[modules.<id>]` to `milepost.toml`; `kb_draft_module`, write the body from the packet and submit it with `kb_update`; `kb_check`; tell the user to run `milepost review <id>` | `INVALID_INPUT` (every file looked like a credential): tell the user to check them and list them in `draft.secret_scan_allow` |
| 9 | Code no module covers | `kb_check` shows `UNCOVERED_DIR`; follow scenario 8 if a module should exist; otherwise ask the user | Do not widen another module's globs without asking |
| 10 | Note has merge-conflict markers | Stop. Do not edit the note | Tell the user a person must resolve the conflict |
| 11 | Before commit | `kb_check`; fix every failure | Never write a `KB-Waive` trailer; ask the user |
| 12 | Finish a task | `kb_sync`; follow each listed route with `kb_update`; run the listed `verify` commands; tell the user which notes now show `draft` and need `milepost review` | `kb_sync` lists nothing: say so and stop |

Token rule that applies to every scenario: prefer `kb_outline` plus a ranged read to reading a whole file, and prefer one `kb_module` call to grepping the module.

Enforcement map, so no step depends on memory alone:
- scenario 1: `SessionStart` hook puts the index in front of the agent;
- scenarios 4, 5, 6: `PostToolUse` hook surfaces covering notes at the moment of the edit;
- scenarios 3, 8, 9, 11: `Stop` hook and `kb_check`, then `pre-commit` and CI;
- every scenario: `next_steps` in each tool response repeats the next call.

### 12.6 Other coding agents

The MCP server (section 11) is not tied to Claude Code: any agent that can start a stdio MCP server can use the tools. Which agents can is a fact about those agents that this spec has not verified; check each agent's current documentation. What does not carry over is the plugin: hooks, the skill and `/kb-init` are Claude Code only. For other agents:
- `templates/AGENTS.md.snippet` carries the playbook as plain instructions for agents that read an `AGENTS.md` file;
- `milepost init`, `milepost sync`, `milepost outline` and `milepost impact` work from a terminal with no agent;
- the enforcement that does not depend on an agent (`pre-commit`, CI, `milepost report`) is the same for everyone.

---

## 13. Dependencies

Core (always installed):
- `typer`, `pydantic>=2`, `pyyaml`, `wcmatch`
- `mcp>=2,<3` (the MCP Python SDK)
- `tree-sitter`, `tree-sitter-typescript`, `tree-sitter-javascript`

Optional extras (the core install has no machine-learning libraries and is roughly a third the size):
- `milepost[search]`: `fastembed` and `numpy`, for meaning-based search. Without it, notes are indexed and searched by keyword only (SQLite FTS5), and `doctor` says so.
- `milepost[all]`: both.

Development:
- `pytest`, `pytest-cov`, `ruff`, `mypy`; install with `uv sync --all-extras`.

Python `>=3.12`.

Lazy import rule: `fastembed` and `numpy` are imported only inside the functions that use them, so commands that do not need them start fast and work when the extra is absent. A missing extra gives a message naming it, never a traceback.

---

## 14. Non-functional requirements

- **Determinism:** `check` and the index rendering produce identical output for identical input on any machine.
- **Speed targets (measured in M6, not guaranteed):** `check` under 1 s for 300 notes; `index` incremental under 10 s for 10 changed notes; `search` under 200 ms on a local index of 5,000 chunks.
- **Context budget (targets, measured in the pilot, not guaranteed):** `kb_overview` under 1,500 tokens for 30 modules; `kb_module` under 2,500; `kb_outline` under 3,000 (200 symbols); `kb_impact` under 1,000 (50 per list); `kb_sync` under 2,000 for a change touching 10 files. Tokens are estimated as characters divided by 4. A tool that would exceed its cap truncates and sets `truncated`.
- **Speed of computed tools:** `outline` under 200 ms for a 2,000-line file; `impact` under 2 s for a repository of 2,000 source files; `status` under 2 s for 30 modules. Unmeasured.
- **Offline:** every command works offline except the first meaning-based search, which downloads the embedding model once.
- **Failure visibility:** no silent failures. Every non-zero exit prints the reason and the next command to run.
- **Coverage:** 90% line coverage on `milepost/services/` and `milepost/core/`, enforced in CI.
- **Logging:** structured JSON logs on stderr when `MILEPOST_LOG=json`; otherwise human text. Logs never include file contents or secrets.

---

## 15. Repository layout for milepost itself

```
milepost/
  pyproject.toml
  README.md
  LICENSE                      # Apache-2.0
  milepost/
    __init__.py
    cli.py                     # Typer app, command wiring only
    config.py                  # section 3
    core/
      hashing.py               # section 5
      notes.py                 # frontmatter parse/validate/write, section 4
      glob.py                  # source set expansion
    services/
      check.py                 # section 6
      index.py                 # section 7
      search.py                # section 7.4
      draft.py                 # section 9.3
      init.py                  # section 9
      review.py                # review
      hooks.py                 # section 10.1
      merge_driver.py          # section 10.3
      render.py                # L1 index rendering, section 8.2
      coverage.py              # UNCOVERED_DIR detection, section 6
      staleness.py             # git-based staleness, section 6.1
      doctor.py                # environment report, section 8
      hook.py                  # hook post-edit, session-start and stop, section 12.4
      outline.py               # section 8.3
      impact.py                # section 8.3
      sync.py                  # section 8.3
      status.py                # section 8.4
      report.py                # section 8.4
    store/
      base.py                  # IndexStore protocol
      sqlite_store.py          # section 7.2
    structure/
      base.py                  # Scanner protocol
      python_scanner.py        # ast-based
      tree_sitter_scanner.py   # TS/JS
    llm/
      # (no model client: Milepost never calls a model)
    mcp_server.py              # section 11
    prompts/
      draft_l2.md
  tests/
    unit/
    integration/
    fixtures/
  templates/                   # copied into user repos by init
  plugin/                      # Claude Code plugin wrapper
```

Rule for implementers: `cli.py` and `mcp_server.py` contain no business logic. They parse input, call a service, and format output.

---

## 16. Out of scope for v1

- Postgres and cloud backends (interface defined in `store/base.py`, implementation deferred).
- codebase-memory-mcp adapter (deferred until its API is verified).
- Cross-repository search.
- A web UI.
- Automatic note updates on every commit (notes are updated by agents during tasks).
- Languages beyond Python, TypeScript, and JavaScript.
- Detecting bugs or wrong agent code. Milepost shows people where to look; it does not judge the change.
- Verifying that a note is true. A stale note is detected; a wrong one is caught only by a person reading it.
- Per-file and per-passage notes (section 1).
- Call graphs and dynamic-import resolution in `impact`; it is a static import graph.
- Forcing a person to read a note. Ownership rules and the report make skipping visible, not impossible.
