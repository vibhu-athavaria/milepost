# milepost Specification

Status: v1 spec. Milestones M0 to M10 are built; see the status table at the top of TASKS.md. Items that are specified but not built are marked "not built". Companion to PROPOSAL.md (the "why"). This file is the "what to build."

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
| LLM access (drafting only) | LiteLLM, model name from env var | The model is chosen by the user through an environment variable; no model names in code |
| MCP server | `mcp` Python SDK (FastMCP), stdio transport | Standard transport for Claude Code |
| Claude Code integration | Plugin wrapper (see section 12) | Ships the MCP server, a usage skill, slash commands, and hooks |
| Plugin entry point | One user-facing command, `/kb-init`; everything else is called by it, by hooks, or by the agent (section 9.4) | Fewest required steps for a developer |
| Agent playbook | Scenario-to-tool steps in section 12.5 are normative; the skill and the CLAUDE.md snippet are derived from them | Agents and humans forget; the steps live in one place and enforcement does not rely on memory |
| Design principle | A note stores only what code cannot tell you: purpose, contracts, invariants, gotchas, intent. Anything derivable from code (symbols, line ranges, importers, tests) is computed live from the working tree by the tools in section 8.3 and is never stored | Stored copies of derivable facts go stale and add review load; computed ones cannot go stale |
| L3 role | No per-file notes are generated. Per-file detail comes from `kb_outline`. An L3 note is a hand or agent written exception (section 4.4) | A model-written note per file multiplies review load and staleness; the outline gives the same pointers for free |
| Human visibility | An agent edit returns a note to `draft`; only `milepost review` sets `reviewed`. `milepost status` and `milepost report` show unreviewed churn and changed code that notes call risky (section 8.4) | Agents now change more code than people read; the notes are the cheapest thing a person can still read |
| Drafting mode | `[draft] mode = "model"` (default: LiteLLM, `MILEPOST_MODEL`) or `"agent"` (milepost hands the draft packet to the coding agent; no key needed), section 9.3 | Lets a team use the agent's own model or choose a cheaper one |
| Note updates after a task | Always written by the agent that did the task, through `kb_update` | It has the change in context; a separate model would have to re-read it |

Revision to PROPOSAL.md section 6: the merge driver does **not** recompute `source_hash`. Recomputing would bless a note that was written against older code. On a frontmatter hash conflict the driver writes the sentinel `CONFLICT` and `milepost check` fails until a person runs `milepost rehash` after reviewing the prose.

### 0.1 Goals

1. **Cheaper, better agent context.** Before a task an agent should get, in a few small calls, the module that owns the work, the rules the code does not show, the exact symbols and line ranges to read, who depends on the file, which tests cover it, and whether the note can be trusted. Targets are in section 14 and are measured in the pilot, not assumed.
2. **Human visibility.** A developer who did not write a change should still be able to see what changed in each module, which notes no person has reviewed, and which changed code the notes call risky.

Both goals use the same artifact: short reviewed notes plus facts computed from git and source. Milepost does not detect bugs and does not verify that a note is true. A person reading the note is the control; milepost keeps notes short, keeps them honest about staleness, and points the reader at the right place (section 16).

---

## 1. Concepts

- **Module:** a named unit of the repo, declared in `milepost.toml`. Each module has one L2 note.
- **Note:** a markdown file under `kb/` with YAML frontmatter and a prose body.
- **Source set:** the files a note describes, given as glob patterns relative to the repo root.
- **Source hash:** a digest over the source set's content, defined in section 4.
- **Staleness:** a note is stale when its recorded `source_hash` differs from the hash computed now.
- **Index:** a derived, rebuildable search database. Never the source of truth.
- **Computed context:** facts derived from source and git at call time (outline, importers, related tests, churn). Never stored, so never stale.

Levels:

| Level | File | Required | Generated by |
|---|---|---|---|
| L1 | `kb/INDEX.md` | yes | `milepost index`: one row per module with a purpose line taken from the module's L2 (section 8.2) |
| L2 | `kb/modules/<module>.md` | yes, per declared module | drafted by a model or by the agent (section 9.3), reviewed by a human, kept current by agents |
| L3 | `kb/files/<path>.md` | optional, exceptions only | agent or human via `kb_update`; never generated for every file |
| L4 | `kb/passages/<slug>.md` | optional, exceptions only | agent or human via `kb_update` |

Per-file detail (symbols, signatures, line ranges) is not a note level. `kb_outline` computes it from the file on demand (section 8.3).

---

## 2. Repository layout after init

```
<repo>/
  milepost.toml                  # config (committed)
  kb/
    INDEX.md                  # L1, generated (committed)
    modules/                  # L2 notes (committed)
    files/                    # L3 notes (committed, optional)
    passages/                 # L4 notes (committed, optional)
    .index/                   # search index (git-ignored)
  .gitattributes              # adds merge driver line for kb/**/*.md (committed)
  .github/workflows/milepost.yml # CI gate (committed)
```

`kb/.index/`, `kb/.progress.json` and `.env` are git-ignored. `init` appends them to `.gitignore`.

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
mode = "model"                         # "model" (default) or "agent"; section 9.3. `milepost init --agent-mode` writes "agent"
provider_model = "${MILEPOST_MODEL}"      # resolved from env var at run time; required when mode = "model"
max_source_bytes = 200000              # per module; larger modules are sampled, see 9.3
exclude = ["**/.env*", "**/*secret*", "**/*.pem", "**/*.key", "**/credentials*"]

[check]
fail_on = "stale"                      # "stale" (default) or "none" (report only)
max_detail_notes = 50                  # warn when L3 plus L4 notes exceed this; a placeholder to tune in the pilot

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
- `draft.mode` is `model` or `agent`.
- `verify` is a list of strings.
- If `draft` is run in `model` mode and `MILEPOST_MODEL` is unset, fail with a message naming the variable.
- `churn_warn_lines` is a non-negative integer; every `agent_trailers` entry is a valid regular expression.
- `max_detail_notes` is a non-negative integer.

Credentials and model choice are never stored in `milepost.toml` or any committed file. The developer sets `MILEPOST_MODEL` and the provider's own environment variable (for example `OPENROUTER_API_KEY` for a model named `openrouter/...`, or `ANTHROPIC_API_KEY`) before using `draft` or `init`. `milepost doctor` reports what is missing.

**`.env` file.** The variables may live in a `.env` file at the repository root instead of the shell. Every command that needs them (`draft`, `init`, `doctor`, `serve`) loads that file at startup with `python-dotenv`. A variable already set in the shell wins over the file. `.env` is git-ignored: `init` appends it to `.gitignore`, and `doctor` warns when a `.env` file exists that git does not ignore. A missing `MILEPOST_MODEL` exits 3 (environment error), not 2.

---

## 4. Note format

### 4.1 Frontmatter (required keys in bold)

```yaml
---
kb_schema: 1                       # required, integer, currently 1
id: module/services                # required; "module/<id>" | "file/<path>" | "passage/<slug>"
level: L2                          # required; L1 | L2 | L3 | L4
title: Services                    # required, one line
status: draft                      # required; draft | reviewed
sources:                           # required for L2 and L3; omitted for L1 and L4
  - backend/app/services/**/*.py
source_hash: sha256:9f2c...        # required for L2 and L3; "CONFLICT" allowed only mid-merge
related: [ai, data]                # optional
written_by: agent                  # required; agent | human | draft-command
written_at: 2026-10-07T09:12:00Z   # required, UTC ISO-8601
reviewed_by: Jane Doe <jane@example.com>   # optional; set only by `milepost review`
reviewed_at: 2026-10-08T14:00:00Z  # optional; set only by `milepost review`
---
```

Status rules, which the visibility features depend on: `milepost review` is the only thing that sets `status: reviewed` (it also writes `reviewed_by` and `reviewed_at` from the git identity). Every `kb_update`, and every draft, sets `status: draft` and removes `reviewed_by` and `reviewed_at`. So an agent's edit to a reviewed note shows up in the pull request as a visible flip from `reviewed` to `draft`.

### 4.2 Body

Free markdown. Recommended sections for L2 (not enforced except that the body must be non-empty):

```
## Purpose          one or two sentences; the first sentence becomes the module's line in INDEX.md
## Entry points     the few places to start reading, with paths
## File map         one line per file, or per folder for large modules, saying what it does
## Owned data
## Invariants       each bullet cites the file (and symbol) in backticks that enforces it
## Gotchas          same: cite the file in backticks
## Related modules
```

Keep an L2 under about 600 words. Cite paths in backticks (`` `routes/auth.py` ``, `` `routes/auth.py::login` ``): `milepost report` and `kb_sync` use those citations to point reviewers and agents at the right bullet when that file changes (section 8.3). Test commands do not go in the note; they are the `verify` list in `milepost.toml`.

### 4.3 Validation

`milepost check` rejects a note when:
- frontmatter is missing or not valid YAML;
- a required key is missing;
- `kb_schema` is not `1`;
- `status` is not `draft` or `reviewed`;
- `source_hash` is `CONFLICT` (message: run `milepost rehash <id>` after review);
- `id` does not match the file path (`kb/modules/services.md` must have `id: module/services`).

### 4.4 When to write L3 and L4

L2 notes are the default unit and there is no per-file note by default: the file map in the L2 and the computed `kb_outline` cover "what is in this file". Write an L3 note only when a single file has gotchas, invariants, or behavior that do not fit in the module note. Write an L4 note only when a point is tied to one narrow passage and would be lost in a longer note. Do not write an L3 for every file you touch. `milepost check` warns with `DETAIL_NOTE_COUNT` when L3 plus L4 notes exceed `check.max_detail_notes` (section 6).

---

## 5. Source hash

Defined precisely so that two machines compute the same value.

1. Expand each glob in the note's `sources` against the repo root with `wcmatch.glob.glob(pattern, root_dir=repo_root, flags=GLOBSTAR | DOTGLOB | FOLLOW)`. Keep regular files only: a symlink to a file counts, a broken symlink or a directory does not. De-duplicate. Then drop every path matched by any `structure.ignore` pattern using `wcmatch.glob.globmatch` with the same flags. Exclude nothing else (dotfiles are included).
2. Sort the resulting repo-relative POSIX paths lexicographically.
3. For each path, read the bytes. Normalize line endings: replace `\r\n` with `\n`, then replace lone `\r` with `\n`. Do not strip whitespace.
4. Compute `file_digest = sha256(normalized_bytes).hexdigest()`.
5. Build the manifest as UTF-8 text, one line per file: `<path>\t<file_digest>\n`.
6. `source_hash = "sha256:" + sha256(manifest_bytes).hexdigest()`.

Edge cases:
- Zero matched files: `source_hash = "sha256:" + sha256(b"").hexdigest()` and `milepost check` emits a warning "module matches no files."
- Symlinks: followed for reading; the resolved path is hashed under the symlink's repo-relative name.
- Binary files: hashed as bytes with no normalization; the line-ending step is skipped when the file contains a NUL byte.

L1 `INDEX.md` has no `source_hash`. It is regenerated by `milepost index` and checked for drift by comparing its content to a fresh render (see section 8.2).

---

## 6. Staleness and the check command

`milepost check` performs, in order:
1. Load and validate config (section 3).
2. Validate every note under `kb/` (section 4.3).
3. For every L2 and L3 note, compute the source hash and compare.
4. For each declared module with no note, emit a warning (not a failure).
5. Compare `INDEX.md` with a fresh render; report drift as a failure.
6. Coverage: for each directory that is a direct child of a `structure.roots` entry and contains at least one non-ignored file in a configured language, emit a warning `UNCOVERED_DIR` when no module's `sources` match any file in it.
7. Orphans: for each L3 note whose `sources` match no files, emit a warning `ORPHAN_NOTE` naming the note id.
8. Detail notes: when the count of L3 and L4 notes exceeds `check.max_detail_notes`, emit a warning `DETAIL_NOTE_COUNT` with the count.
9. Citations: for each L2 and L3 note, every path cited in backticks in Entry points, File map, Invariants or Gotchas must match a file in the repository (equal, or a suffix after `/`); a cited directory (trailing `/`) must exist; and for a cited `file::symbol` in a uniquely matched file, the symbol's last name must appear in the file text. The test is deliberately lenient so it flags only what is clearly absent. A backtick span is treated as a path only if it ends in `/`, has an extension, or (without a `/`) ends in a known file extension, so routes like `api/users`, phrases like `and/or` and symbols like `Class.method` are ignored; a leading `./` and a `:42` line suffix are dropped. Otherwise emit a warning `CITATION_BROKEN`. At most 200 citations per note are checked, and an unreadable file is skipped, never an error. This catches invented details; it does not prove a true citation supports its claim.
10. Unreviewed churn: for each note that has been reviewed at least once, when the lines changed in its source files since its last review (section 8.4) exceed `visibility.churn_warn_lines`, emit a warning `UNREVIEWED_CHURN`. Never a failure, and never emitted for a note no person has reviewed yet, so a fresh `init` does not warn.

Output: human text by default; `--format json` emits a list of findings `{severity, code, path, message}`.

Exit codes:
- `0`: no failures.
- `1`: at least one failure (stale note, invalid note, `CONFLICT`, INDEX drift).
- `2`: config or usage error.

Waivers: a commit or PR may carry the trailer `KB-Waive: <note-id> <reason>`. `milepost check --ci --base <ref>` reads the trailers in commits between `<ref>` and `HEAD` and downgrades a stale finding for that note id to a warning. A waiver without a reason is an error.

`--ci --base <ref>` also fails when a changed source file belongs to a module that has a note, and that note is stale, even if the note file itself was not changed.

In `--ci` mode a stale note whose source set contains no file changed in the range stays a warning, so debt that already exists on the base branch does not block unrelated PRs. Only a stale note covering a changed file fails.

`--ci --base <ref>` also upgrades two warnings to failures, scoped to the diff range so existing debt does not block unrelated PRs:
- `UNCOVERED_DIR` fails when the directory gained its first source file in the range. Waiver trailer: `KB-Waive: dir:<path> <reason>`.
- `ORPHAN_NOTE` fails when the note's source file was deleted or renamed in the range. Waiver trailer: `KB-Waive: <note-id> <reason>`.

A declared module with no note still only warns, locally and in CI.

---

## 7. Index

### 7.1 Contents

Chunks are created from:
- each L1 entry (one chunk per module line);
- each L2 note split on `##` headings (chunk = heading + body, max 2,000 characters; longer sections split on paragraph boundaries);
- each L3 and L4 note the same way.

Each chunk stores: `chunk_id`, `note_id`, `level`, `heading`, `text`, `source_hash`, `embedding`.

### 7.2 Storage (SQLite)

```sql
CREATE TABLE notes (note_id TEXT PRIMARY KEY, level TEXT, status TEXT, source_hash TEXT, content_sha TEXT, indexed_at TEXT);
CREATE TABLE chunks (chunk_id INTEGER PRIMARY KEY, note_id TEXT, heading TEXT, text TEXT);
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, heading);   -- rowid = chunk_id, kept in step by the store
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);          -- embedding_model, embedding_dim
CREATE TABLE chunk_vectors (chunk_id INTEGER PRIMARY KEY, embedding BLOB NOT NULL);   -- float32 x dim from config
```

### 7.3 Rebuild rules

- `milepost index` is incremental: a note is re-chunked and re-embedded only when its `content_sha` (sha256 of the file bytes) changed.
- `milepost index --rebuild` drops and recreates all tables.
- A schema or model change (different `embedding_model` or `embedding_dim`) forces `--rebuild`; the stored model name is kept in a `meta` table and compared on every run.
- The index never affects `milepost check`. Check reads files only.

### 7.4 Search

`milepost search <query> [--level L2] [--k 5]`: hybrid. Run FTS5 BM25 and vector KNN (k = 20 each), merge with reciprocal rank fusion (k = 60), return the top `k`. Each result: `note_id`, `heading`, `score`, `snippet` (max 300 characters), `status`.

The vector half is an exact scan: it loads the candidate vectors, computes cosine similarity against the query, and keeps the top results. That is milliseconds at the intended scale (a few hundred notes, a few thousand chunks). It is not meant for hundreds of thousands of chunks; a larger deployment would use the Postgres backend (pgvector) deferred in section 16.

The keyword query drops common English filler words (a fixed list in the store) and ORs the remaining terms, so that words like "how" and "the" do not outrank real matches; the vector search sees the whole query. Without this, a query whose keyword hits were all filler pushed the right note out of the fused top results (found with the 20-note fixture KB).

---

## 8. Commands

All commands accept `--repo <path>` (default: nearest ancestor with `milepost.toml`). All print to stdout; diagnostics go to stderr. `--json` is available on every command that prints results.

| Command | Purpose | Notes |
|---|---|---|
| `milepost init [--dry-run] [--backend sqlite] [--seed-docs PATH ...] [--modules ID,...] [--yes]` | Scaffold and draft (section 9) | Never overwrites existing files; `--modules` and `--yes` are what the plugin's `/kb-init` uses |
| `milepost check [--ci --base REF] [--format text\|json]` | Validate and detect staleness (section 6) | Exit codes in section 6 |
| `milepost index [--rebuild]` | Write `kb/INDEX.md`, then rebuild or update the search index (section 7) | Safe to run from git hooks |
| `milepost draft <module-id> [--force]` | (Re)draft one L2 note with `status: draft` | Refuses to overwrite `reviewed` unless `--force`; `model` mode only (agent mode drafts through `kb_draft_module`) |
| `milepost review <note-id>` | Set `status: reviewed` after human sign-off | Does not change `source_hash`; records `reviewed_by` and `reviewed_at` from the git identity (exit 3 if it is not set); refuses a stale note and a `CONFLICT` note; rewrites `INDEX.md` because the status column changes |
| `milepost outline <path> [--json]` | Symbols, signatures and line ranges of one file, computed now | Section 8.3 |
| `milepost impact <path> [--json]` | Files that import this file and the tests likely to cover it, computed now | Section 8.3 |
| `milepost sync [--base REF] [--json]` | What changed and which notes to update, and how | Section 8.3; read-only |
| `milepost status [--json]` | Per module: review state and unreviewed churn | Section 8.4; read-only |
| `milepost report --base REF [--format markdown\|json]` | Review aid for a change range | Section 8.4; read-only, always exits 0 |
| `milepost rehash <note-id>` | Recompute `source_hash` for a note marked `CONFLICT` or intentionally updated | Prints the old and new hash and the current manifest (path and short digest; the old manifest cannot be recovered from a hash alone); asks for confirmation, and requires `--yes` in non-interactive shells (exit 2 otherwise) |
| `milepost search <query> [--level L] [--k N]` | Hybrid search | Section 7.4 |
| `milepost hooks install \| uninstall` | Manage git hooks and merge driver config | Section 10 |
| `milepost merge-driver %O %A %B %P` | Invoked by git for `kb/**/*.md` | Section 10.3 |
| `milepost serve` | Run the MCP server on stdio | Section 11 |
| `milepost doctor` | Print environment: Python, git, SQLite FTS5 available, fastembed model cached, `MILEPOST_MODEL` set, the provider key variables for that model present (via `litellm.validate_environment`, verified to name `OPENROUTER_API_KEY` and `ANTHROPIC_API_KEY`), and whether a `.env` file is git-ignored | Read-only; exit 3 when a variable needed for drafting is missing |
| `milepost scan [--json]` | List candidate modules under `structure.roots` that no declared module covers (same scan as init step 3) | Read-only; never edits config |
| `milepost hook session-start` | Print the index and a reminder as session context | Used by the plugin hook, section 12.4; always exits 0 |
| `milepost hook post-edit` | Read Claude Code hook JSON on stdin, find the edited path, print the notes that cover it | Used by the plugin hook, section 12.4; always exits 0 |
| `milepost hook stop` | Run `milepost check`, print findings in hook format | Used by the plugin hook, section 12.4 |

### 8.1 Exit codes (all commands)

`0` success, `1` a check or operation found failures, `2` usage or config error, `3` environment error (missing dependency, unreadable repo), `4` LLM provider error.

### 8.2 INDEX.md rendering

Deterministic, so `check` can compare. Format:

```markdown
# Codebase index

| Module | Purpose | Status | Note |
|---|---|---|---|
| services | Business logic behind the API routes; owns billing and enrollment rules. | reviewed | kb/modules/services.md |
```

Rows are sorted by module id. The purpose is the first sentence of the note's `## Purpose` section, whitespace collapsed and cut to 160 characters; it is `(no note yet)` when the note is missing and `(no Purpose section)` when it has none. Renders from notes only; no timestamps. Because the purpose lives in the L2, editing a Purpose changes INDEX.md and `check` reports the drift until `milepost index` rewrites it.

### 8.3 Computed context: `outline`, `impact`, `sync`

These read the working tree and git at call time. Nothing they return is stored in `kb/` or the index, so none of it can go stale.

**`outline <path>`.** Parses one file and lists its symbols in line order. Python uses the stdlib `ast`; TypeScript and JavaScript use tree-sitter. Each symbol has: `name` (qualified for methods, `Class.method`), `kind` (`function`, `class`, `method`, `interface`, `type`, `const`), `signature` (the first line of the definition), `doc` (first docstring or leading comment line, at most 120 characters, may be empty), `start_line`, `end_line`. At most 200 symbols are returned; beyond that `truncated` is true. The path must be inside the repository. An unsupported extension is a usage error (exit 2, `INVALID_INPUT` in MCP) whose message includes the file's line count, so the caller knows whether to read it whole.

**`impact <path>`.** Uses the structure scanners (section 15) over source files in the configured languages, excluding `structure.ignore`, to find internal imports that target `<path>`. The file list comes from git (tracked files plus untracked files that are not ignored), so virtualenvs, build output and agent worktrees that git ignores are never read; outside a git repository it falls back to globbing. Only files whose text contains the target's module name are parsed. Measured on a real repository of about 2,000 tracked files: under 1 second per call, where listing by glob took about 50 seconds because it also read agent worktree copies. Returns: `importers` (files importing it); `tests` (importers that look like tests, plus files elsewhere whose name contains the target's stem and that look like tests, each marked `via: import` or `via: name`); `modules` (declared modules whose sources cover the path, with their `verify` commands); `notes` (covering note ids). A file looks like a test when its path contains `tests/`, `test/` or `__tests__/`, or its name matches `test_*.py`, `*_test.py`, `*.test.*` or `*.spec.*`. Each list is capped at 50 with `truncated` set. This is a static import graph: dynamic imports, string-based plugin loading and framework wiring are not seen, and the response says so.

**`sync [--base REF]`.** Lists files changed in the working tree against `HEAD` (staged, unstaged and untracked), or against `--base REF...HEAD` when given. A rename counts as one delete plus one add. For each changed file outside `kb/` it returns the declared modules and notes that cover it (a deleted path is matched against the module globs as a string), each note's `stale` flag and `source_hash_now`, and the routes below. It also returns the `verify` commands of every affected module and a `next_steps` list. Routing is rule-based and deterministic; no model is involved:

| Change | What to update |
|---|---|
| File modified in a module | The module's L2: re-read the file, edit Purpose, File map, Invariants or Gotchas if the change affects them, otherwise call `kb_update` with the unchanged body to refresh the hash. Any L3 covering the file: same |
| File added in a module | The L2 File map (add a line); Entry points if it is a new starting point |
| File deleted or renamed | The L2 File map (remove or rename the line). An L3 for the old path becomes `ORPHAN_NOTE`: tell the user, do not delete it |
| Path covered by no module | `UNCOVERED_DIR` guidance: declare a module (playbook 8) or ask the user |
| A backticked path cited in an Invariants or Gotchas bullet is among the changed files | Name that bullet and note id: "confirm this still holds" |
| File under `kb/` | Nothing |

Citation matching: a cited path matches a changed file when it equals the file's path or is a suffix of it after a `/`, and exactly one file in the module's source set has that suffix. Ambiguous citations are skipped, not guessed.

### 8.4 Human visibility: `status`, `report`

Both are derived from git and the notes, are read-only, and never fail a build. They exist so a person who did not write a change can see where attention is needed.

**Review baseline.** For a note, the baseline is the most recent commit in the current history that recorded a review: one that added or removed a `reviewed_at` line and left the note `status: reviewed` (notes reviewed by hand, without `reviewed_at`, fall back to the latest commit that touched the status line). A typo fix or a rehash on an already-reviewed note does not reset it. This survives squash merges and rebases, unlike a stored commit id. No baseline means no person has reviewed the note. Churn counts every file in the module's source globs that changed since the baseline, including files deleted or moved away since.

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
5. **Draft:** in `model` mode, for each declared module without a note, call `milepost draft`; in `agent` mode, skip and tell the developer the agent will draft through `kb_draft_module`. Skipped with `--dry-run`, which prints module count and estimated tokens (file bytes / 4 as a rough estimate).
6. **Index:** `milepost index`.
7. **Report:** print the CLAUDE.md snippet location, the CI template location, and the next command (`milepost review <id>` per draft).

### 9.2 Idempotency

Re-running `init` creates only what is missing. Existing `kb/modules/*.md` files are not modified. Existing `milepost.toml` is not modified unless `--force-config`, with one exception: `--modules` appends `[modules.<id>]` tables for modules not yet declared and changes nothing else in the file. That is how a module is added after the first run.

`--yes` skips confirmation prompts. Without it, in an interactive shell, `init` prints the module list, the files that would be sent for drafting, and the token estimate, and asks once.

### 9.3 Drafting

**Modes.** `draft.mode = "model"` (default) calls the model named by `MILEPOST_MODEL` through LiteLLM, as described below. `draft.mode = "agent"` never calls a model from milepost and needs no key: `milepost init` scaffolds, declares modules and builds the index but skips drafting, and the coding agent drafts through `kb_draft_module`. In agent mode that tool returns a *draft packet* instead of writing a note: the drafting prompt, the collected sources (after `draft.exclude`, the size budget and the secret scan), and an instruction to write the body and submit it with `kb_update`. `kb_update` is allowed to create a missing L2 note in agent mode, only for a declared module, and always writes `status: draft`. In agent mode `draft.exclude` and the secret scan protect only the packet; the agent can still read any file with its own tools, so they are not a guarantee. Updates after a task are written by the agent in both modes (section 0).

- Input: the module's source files, concatenated with headers `=== path ===`, after applying `draft.exclude`. If the total exceeds `max_source_bytes`, include the structure summary (imports, top-level symbols) for every file and full text only for the first N files that fit, and state the truncation in the note body.
- Prompt: stored in `milepost/prompts/draft_l2.md` (not inline in code). It instructs the model to write only what is verifiable from the provided code, to mark uncertainty explicitly, to avoid describing behavior not present in the input, to cite file paths in backticks, to include a File map, and to stay short.
- Output validation: the response must parse into the note body; frontmatter is written by milepost, never by the model.
- Provider errors: retried 2 times with backoff; then exit 4 with the module id. A partial run leaves completed notes in place and records progress in `kb/.progress.json`.
- Seed documents (`--seed-docs`): included in the prompt with the label "documentation, not verified against code." Notes derived from them must say so in the body.

### 9.4 Plugin entry point: `/kb-init`

`/kb-init` is the only slash command the plugin ships. A developer runs it once; every other step is called from it, by hooks, or by the agent. `plugin/commands/kb-init.md` instructs the agent to:

1. Run `milepost doctor --json`. If anything needed for drafting is missing (`MILEPOST_MODEL` or the provider key), tell the developer exactly which variables to set and stop.
2. Run `milepost scan --json` and `milepost init --dry-run --modules <all candidates>`. Show the candidate modules, the files that would be sent, and the estimated tokens, and ask once which modules to keep.
3. Run `milepost init --yes --modules <confirmed ids>`: scaffold, declare the modules, install hooks and the merge driver, write the CI workflow, draft the L2 notes, and build the index.
4. Report the one step that needs a person: read each draft under `kb/modules/`, run `milepost review <id>` for each one that is right, then commit `milepost.toml`, `kb/`, `.gitattributes`, and `.github/workflows/milepost.yml`.

The command does not print the CLAUDE.md snippet, because the plugin's skill and hooks carry the same rules. Re-running is safe (section 9.2) and is how modules are added later: the scan lists only undeclared candidates. `milepost check` is not a slash command; agents use `kb_check` and the `Stop` hook, and developers run the CLI.

### 9.5 Security

- Files matching `draft.exclude` are never read for drafting.
- Before sending, milepost scans the input for common secret patterns (AWS key ids, private key headers, `password=`/`token=` assignments with long values). A match aborts that module with exit 4 and names the file, not the value.
- `--dry-run` lists every file that would be sent, so a reviewer can check the set before any network call.
- The provider endpoint is whatever LiteLLM is configured for via environment variables; milepost adds no endpoint of its own.

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
2. For frontmatter, take each key from ours or theirs when only one side changed it. When both changed a key to different values, keep the value from ours and set `source_hash: CONFLICT` if the key is `source_hash`; for other keys, keep ours.
3. A review only counts for the prose the reviewer read. If the merged status is `reviewed` but the merged body is not exactly the body of the side that holds that review (and not the unchanged base body), the driver sets `status: draft` and removes `reviewed_by` and `reviewed_at`. An edit by one side always wins over a review by the other: a status that is `draft` on one side and unchanged on the other becomes `draft`.
4. Write the result to `%A`.
5. `kb/INDEX.md` is generated, so the driver keeps ours and exits 0; `milepost index` (run by the `post-merge` hook) regenerates it, and `check` reports `INDEX_DRIFT` until it has. A file with no frontmatter is merged as plain text.

Result: a merge never silently chooses a `source_hash`. A conflicted hash fails `milepost check` until `milepost rehash` runs after review.

---

## 11. MCP server

Started by `milepost serve` over stdio. Built with FastMCP. Each tool returns text (markdown) and a structured object with the same data. Responses are bounded: a single note returned at most 20,000 characters; search returns at most 10 results.

Every response is also size-bounded by the per-tool caps in section 14. Every response also carries `next_steps`: a list of short instructions computed deterministically from repository state (never by a model), for example "3 notes cover this path; call kb_update on each after you change it". The rules for each tool are in section 12.5.

| Tool | Input | Output |
|---|---|---|
| `kb_overview` | none | L1 index markdown, plus a count of stale notes and the current branch name |
| `kb_module` | `id: str` | Note frontmatter and body, `source_hash_now` (hash of the sources as they are on disk), the module's `verify` commands, plus `related` note summaries (id, title, status) |
| `kb_file` | `path: str` | Every L2 and L3 note whose sources match the path, each with `source_hash_now` and a `stale` flag, plus any L3 note for that path |
| `kb_search` | `query: str`, `level: str \| None`, `k: int = 5` | Hybrid search results (section 7.4) |
| `kb_update` | `id: str`, `body: str`, `read_hash: str` (required for L2 and L3) | Writes the note with `status: draft` (and removes `reviewed_by` and `reviewed_at`), recomputes `source_hash` for L2 and L3, returns `milepost check` findings for that note. It cannot set `reviewed`; only `milepost review` can |
| `kb_check` | none | Same findings as the CLI, including `UNCOVERED_DIR` and `ORPHAN_NOTE` warnings |
| `kb_draft_module` | `id: str` | Drafts the L2 note for a module already declared in `milepost.toml`, with `status: draft` (model mode), or returns a draft packet (agent mode); section 11.3 |
| `kb_outline` | `path: str` | Symbols, signatures and line ranges of the file, computed now (section 8.3) |
| `kb_impact` | `path: str` | Importers, likely tests, covering modules and notes (section 8.3) |
| `kb_sync` | `base: str \| None` | Changed files, the notes to update and how, and the `verify` commands (section 8.3) |

### 11.1 Write discipline

`kb_update` recomputes `source_hash` from the working tree at the moment of the write. That is correct only if the agent has read the current source before writing. To enforce this, `kb_module` and `kb_file` return `source_hash_now`, and `kb_update` for an L2 or L3 note requires that value back as `read_hash`. If `read_hash` differs from the hash of the working tree at write time, the source changed after the agent read it and the write is rejected with `STALE_READ`. The agent must read again and retry.

This proves the agent fetched the note after the last source change; it does not prove the agent understood the code. Reading source files directly is still required by the playbook (section 12.5).

A `kb_update` whose body is identical to the current body is allowed. It refreshes `source_hash` and `written_at` and is how an agent records "re-read the new source, the note is still accurate".

`kb_update` rejects:
- writes to an id that does not exist unless `level` is L3 or L4, or `draft.mode` is `agent` and the id is a declared module (new L2 notes otherwise come from `kb_draft_module` or `milepost draft`);
- an L2 or L3 write with a missing or mismatched `read_hash` (`STALE_READ`);
- bodies longer than 20,000 characters;
- any change to frontmatter other than the body, `status` (always set to `draft`), `source_hash`, `written_by`, `written_at`, and the removal of `reviewed_by` and `reviewed_at`; `kb_update` never changes `sources`, `id`, or `kb_schema`.

### 11.2 Errors

Tool errors return a structured error `{code, message}` with codes `NOT_FOUND`, `INVALID_INPUT`, `CONFLICT`, `STALE_READ`, `ENVIRONMENT`. Stack traces are logged to stderr only.

### 11.3 `kb_draft_module`

Lets an agent create the L2 note for a new module in the same change as the code, without a CLI round trip.

- Precondition: the module id is declared in `milepost.toml`. The tool never edits config; the agent adds the `[modules.<id>]` entry as an ordinary file edit first. An undeclared id returns `NOT_FOUND` with `next_steps` naming the config entry to add.
- Refuses with `CONFLICT` if a note for the module already exists. Redrafting stays a human action (`milepost draft --force`).
- Runs the same drafting service as `milepost draft` (section 9.3): `draft.exclude`, the secret scan, and the size budget all apply, and the note is written with `status: draft` and `written_by: draft-command`.
- In model mode it needs `MILEPOST_MODEL`; if unset, returns `ENVIRONMENT` naming the variable. It sends source to the configured LLM provider, as `milepost draft` does, and the tool description says so. In agent mode it returns the draft packet described in section 9.3 and calls no model.
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
| 5 | Add a file to an existing module | `kb_module`; read the new source; `kb_sync`; `kb_update` on the L2 (File map, and Entry points if it is a new starting point); `kb_check` | none |
| 6 | Rename or delete a file | `kb_impact` on the old path before the change (who imports it); after the change, `kb_sync` and `kb_update` on each covering L2; `kb_check` | `ORPHAN_NOTE` for an L3: tell the user, do not delete the note |
| 7 | Learned a gotcha or invariant | `kb_update` on the L2 (Gotchas or Invariants, citing the file in backticks) after reading the source it refers to; an L3 or L4 only as section 4.4 allows | none |
| 8 | New module | Add `[modules.<id>]` to `milepost.toml`; `kb_draft_module` (in agent mode, write the body from the packet and submit it with `kb_update`); `kb_check`; tell the user to run `milepost review <id>` | `ENVIRONMENT` (`MILEPOST_MODEL` unset, model mode): tell the user which variable to set |
| 9 | Code no module covers | `kb_check` shows `UNCOVERED_DIR`; follow scenario 8 if a module should exist; otherwise ask the user | Do not widen another module's globs without asking |
| 10 | Hash is `CONFLICT` | Stop. Do not edit the note and do not rehash | Tell the user the note needs review and `milepost rehash <id>` |
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

Runtime:
- `typer`, `pydantic>=2`, `tomli` (stdlib `tomllib` on 3.11+ suffices; use it), `pyyaml`, `wcmatch`
- `mcp` (FastMCP)
- `litellm` (drafting only; imported lazily so other commands do not need it)
- `fastembed`
- `numpy`
- `python-dotenv` (loads `.env`, section 3)
- `tree-sitter`, `tree-sitter-typescript`, `tree-sitter-javascript`

Development:
- `pytest`, `pytest-cov`, `ruff`, `mypy`

Python `>=3.12`.

Lazy import rule: `litellm` and `fastembed` are imported inside the functions that use them. Commands that do not need them (`check`, `review`, `hooks`) start fast and work without the model stack.

---

## 14. Non-functional requirements

- **Determinism:** `check` and `INDEX.md` rendering produce identical output for identical input on any machine.
- **Speed targets (measured in M6, not guaranteed):** `check` under 1 s for 300 notes; `index` incremental under 10 s for 10 changed notes; `search` under 200 ms on a local index of 5,000 chunks.
- **Context budget (targets, measured in the pilot, not guaranteed):** `kb_overview` under 1,500 tokens for 30 modules; `kb_module` under 2,500; `kb_outline` under 3,000 (200 symbols); `kb_impact` under 1,000 (50 per list); `kb_sync` under 2,000 for a change touching 10 files. Tokens are estimated as characters divided by 4. A tool that would exceed its cap truncates and sets `truncated`.
- **Speed of computed tools:** `outline` under 200 ms for a 2,000-line file; `impact` under 2 s for a repository of 2,000 source files; `status` under 2 s for 30 modules. Unmeasured.
- **Offline:** every command except `init` (drafting step) and `draft` in model mode works offline.
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
      review.py                # review and rehash
      hooks.py                 # section 10.1
      merge_driver.py          # section 10.3
      render.py                # INDEX.md rendering, section 8.2
      coverage.py              # UNCOVERED_DIR and ORPHAN_NOTE detection, section 6
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
      client.py                # LiteLLM wrapper, retries, secret scan
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
- Automatic note updates on every commit (notes are updated by agents during tasks and by `draft` on demand).
- Languages beyond Python, TypeScript, and JavaScript.
- Detecting bugs or wrong agent code. Milepost shows people where to look; it does not judge the change.
- Verifying that a note is true. A stale note is detected; a wrong one is caught only by a person reading it.
- Per-file model-written notes for every file (section 0, L3 role).
- Call graphs and dynamic-import resolution in `impact`; it is a static import graph.
- Forcing a person to read a note. Ownership rules and the report make skipping visible, not impossible.
