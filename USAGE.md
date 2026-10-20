# Using Milepost

This is the how-to. For what Milepost is and why, start with the [README](README.md).

Milepost is an MVP: it works end to end as a Claude Code plugin loaded from a local checkout, and as a command-line tool. It is not on PyPI, and nobody has yet measured whether it saves agent effort or keeps people closer to their code (that is the pilot, [PILOT.md](PILOT.md)).

**Jump to:** [Concepts](#concepts-in-one-minute) · [Try the plugin](#try-the-plugin) · [Use only the command line](#use-only-the-command-line) · [Day to day](#day-to-day) · [Commands](#command-reference) · [Findings](#what-check-reports) · [Configuration](#configuration) · [Environment](#environment-variables) · [Troubleshooting](#troubleshooting) · [Not built yet](#what-is-not-built-yet)

---

## Concepts in one minute

- A **module** is a named part of your repository, declared in `milepost.toml` as a set of file globs. Each module gets one **module note** (L2) at `kb/modules/<id>.md`.
- A **note** is a markdown file with YAML frontmatter that records which source files it describes (`sources`, mirroring `milepost.toml`). There is one note per module. Nothing derived from the code is stored in it.
- A note is **stale** when a file it covers changed after the note was last touched, judged from git history (and uncommitted edits). It is a warning by default.
- A note's **status** is `draft` (written by a model or an agent, unreviewed) or `reviewed` (a person ran `milepost review`). Every agent edit sets a note back to `draft`.
- The module index (L1) is not a file: it is built from the notes whenever it is needed, one row per module. `milepost overview` prints it.
- There are no per-file notes. Per-file detail is not a note: `milepost outline` and `milepost impact` read it from the code when asked.

A complete note, with every frontmatter field, is in [templates/note.md.template](templates/note.md.template).

---

## Try the plugin

**You need:** [uv](https://docs.astral.sh/uv/), Python 3.12, [Claude Code](https://claude.com/claude-code), and a git repository to try it on. Claude Code writes the first drafts itself, so no API key or model setup is needed.

The plugin is the [plugin/](plugin/) folder of your clone of this repository (below, `~/milepost` stands for wherever you cloned it) and it runs that checkout of milepost. That means it must be loaded in place with `--plugin-dir`. Installing it from a marketplace, which copies it elsewhere, needs a published release and does not work yet.

### 1. Set up

Clone this repository once and set it up:

```bash
git clone https://github.com/vibhu-athavaria/milepost ~/milepost && cd ~/milepost
uv sync --python 3.12 && uv tool install --editable .      # the second command puts `milepost` on your PATH
```

### 2. Start Claude Code with the plugin

```bash
cd /path/to/your/repo
claude --plugin-dir ~/milepost/plugin
```

Approve the MCP server and hooks if asked. Run `/mcp`: `milepost` should be listed with ten `kb_*` tools.

### 3. Create the knowledge base

Run **`/milepost:kb-init`**. It will:

1. check your environment;
2. list the candidate modules found under `src`, `app`, `backend/app`, `packages` and `apps`;
3. show the files that would be sent for drafting and the token estimate, then **ask once** which modules to keep;
4. declare those modules in `milepost.toml`, install the git hooks and merge driver, write the CI workflow, and build the search index;
5. then Claude Code reads each module's source and writes one draft note per module through the `kb_draft_module` and `kb_update` tools. This is the step that spends tokens, and it takes a minute or so per module.

Claude Code may ask your permission to run the `milepost` commands and tools; approve them. Nothing is written before you answer the one question in step 3. Notes stay `draft` until you review them.

### 4. Review

Read each note under `kb/modules/`. Fix what is wrong, then approve it:

```bash
milepost review module/<id>
```

(If you skipped `uv tool install`, use `uv run --project ~/milepost milepost review module/<id>`.) Then commit `milepost.toml`, `kb/`, `.gitignore`, `.gitattributes` and `.github/workflows/milepost.yml`.

### 5. Work

Nothing more to run. During a session:

- the agent is shown the module index when the session starts;
- when it edits a covered file it is told which notes describe that file;
- if it tries to finish while a note is stale for files it changed, it is blocked once and told what to update;
- its note edits are saved as `draft` and show up in your pull request as a flip from `reviewed`, so you can re-review them.

### What to expect on a first run

- Search is keyword-only until you install the `search` extra; the first meaning-based search then downloads a ~130 MB model.
- Each hook starts `uv run`, which adds a fraction of a second. To remove it, run `uv tool install --editable ~/milepost` and change the commands in `plugin/hooks/hooks.json` to plain `milepost hook ...`.
- Drafting shows a module's source to Claude, as everything else it reads is shown. Only run it on code you are allowed to share with your Claude provider, and read the dry-run list first.
- The CI workflow that `init` writes installs milepost from PyPI, which does not exist yet, so that step fails in CI. Edit `.github/workflows/milepost.yml` to install from your checkout or a git URL, or leave the workflow out of a first trial.

---

## Pause Milepost

Set `MILEPOST_DISABLED=1` in the shell that starts Claude Code:

```bash
MILEPOST_DISABLED=1 claude --plugin-dir ~/milepost/plugin
```

The plugin hooks print nothing, the MCP server starts with no tools (its instructions say it is paused), and the git hooks exit 0 without running. Commands you type yourself (`milepost check`, `status`, and so on) still run. Unset the variable and restart Claude Code to resume: the MCP server reads it once at startup. Accepted values are `1`, `true`, `yes` and `on`. Git hooks installed by an older version do not know the variable, so run `milepost hooks install` once to refresh them.

Pausing does not hide `kb/`, which is plain markdown the agent can still read, nor any Milepost lines in `CLAUDE.md` or `AGENTS.md`. For a fair comparison use the worktrees below.

## Compare the same task with and without Milepost

The pause switch is not enough for a fair comparison, because the notes stay readable. Run the same task in two sessions, each in its own worktree of the same commit, so the notes and settings of one cannot leak into the other.

```bash
cd ~/your-repo
git worktree add ../task-with    -b ab-with    <commit>
git worktree add ../task-without -b ab-without <commit>

# Without: delete everything Milepost added, so the agent has nothing to read.
cd ../task-without
git rm -rq --ignore-unmatch kb milepost.toml .mcp.json
ls kb milepost.toml 2>/dev/null   # must print nothing; if it lists files, delete them by hand
# Also remove the Milepost lines from CLAUDE.md / AGENTS.md if you added the snippet.
git commit -qm "ab: remove milepost" && claude

# With: same commit, plugin loaded.
cd ../task-with
claude --plugin-dir ~/milepost/plugin
```

Give both sessions the identical prompt, then compare the token count, the number of turns, whether the result passes your tests, and how long a reviewer needs to review each diff. Run each arm more than once, since a single run is noise.

Two details that matter:

- Git hooks live in the shared git directory, so a hook installed with `milepost hooks install` also runs in the "without" worktree. Hooks from this version do nothing when the checkout has no `milepost.toml`. If you installed them with an older version, run `milepost hooks install` once (`milepost doctor` tells you when they are outdated), or the old pre-commit will block commits in the "without" worktree.
- `kb/` is ordinary markdown. If you leave it in the "without" copy, the agent can read the notes as plain files and the comparison is no longer fair.

## Use only the command line

You don't need the plugin to use milepost.

```bash
git clone https://github.com/vibhu-athavaria/milepost ~/milepost && cd ~/milepost
uv sync --python 3.12
uv tool install --editable .          # puts `milepost` on your PATH (optional)
```

Then, in your repository:

```bash
milepost scan                                      # what modules would it propose?
milepost init --dry-run --modules api,core         # which files would be sent, how many tokens
milepost init --yes --modules api,core             # create the knowledge base and draft the notes
milepost check                                     # is every note current?
milepost review module/api                         # after you have read it
```

### Optional extras

The default install is lean (no machine-learning libraries, no downloads). One extra adds a capability:

| Extra | Adds | Install |
|---|---|---|
| `search` | meaning-based search over the notes (local embeddings; the first use downloads a ~130 MB model). Without it, search is keyword-only | `uv tool install --editable ".[search]"` |

`milepost doctor` says which are missing. For development use `uv sync --all-extras`.

Without `uv tool install`, prefix commands with `uv run --project ~/milepost`. Every command accepts `--repo PATH`; the default is the nearest parent directory containing `milepost.toml`.

---

## Day to day

### If you are the agent (the plugin does this for you)

The playbook is [SPEC.md](SPEC.md) section 12.5. In short:

| When | Call |
|---|---|
| Starting a task | `kb_overview`, then `kb_module` for the owning module, `kb_outline` for the files to read (then read only those line ranges), `kb_impact` for the files to change |
| After a change | the module's `verify` commands, then `kb_sync`, then `kb_update` on each note it lists, then `kb_check` |
| A new module | add it to `milepost.toml`, then `kb_draft_module`; write the note from the sources it returns and save it with `kb_update` |
| A note you cannot reconcile, or a merge conflict in a note | stop; tell a person. Never mark a note reviewed, never write a `KB-Waive` |

Each tool's answer ends with `next_steps`: follow them.

### If you are the developer

- **Once:** review each module note, then `milepost review module/<id>`.
- **In pull requests:** read the note diff first. It should state invariants and gotchas, not restate the code. A note that flipped from `reviewed` to `draft` needs a person.
- **When CI fails on a stale note:** update the note. Use a waiver (below) only when the note is still accurate, and say why.
- **When a merge conflicts in a note:** resolve the markers in the prose like any other file. (Notes store no hash, so two pull requests touching different files of one module merge cleanly.)
- **Now and then:** `milepost status` shows which modules have moved furthest since someone last reviewed their note.

### If you are the reviewer

`milepost report --base origin/main` (or the CI job summary) lists: notes changed (and any `reviewed` to `draft` flips), notes stale for the changed files, changed source files no module covers, invariants and gotchas that cite changed files, and modules with a lot of unreviewed change. Start there.

### Waivers

A failing finding can be waived with a trailer in a commit message. A waiver without a reason is an error.

```
KB-Waive: module/services prose is still accurate after this refactor
KB-Waive: dir:app/payments scratch code, a module comes later
```

---

## Command reference

| Command | Purpose |
|---|---|
| `milepost init [--dry-run] [--modules ID,...] [--yes] [--force-config] [--no-hooks]` | Scaffold the knowledge base, declare the named modules, install the git hooks, build the index, and list the modules Claude should write notes for. Writes nothing with `--dry-run` |
| `milepost scan [--json]` | List candidate modules no declared module covers. Read-only |
| `milepost check [--ci --base REF] [--format text\|json] [--no-churn]` | Validate notes and detect staleness. Exit 1 on failures. `--no-churn` skips the slower unreviewed-churn warning |
| `milepost review NOTE_ID` | Mark a note reviewed by you (records your git identity and the time). Refuses a stale note |
| `milepost overview` | Print the module index (one line per module), built from the notes |
| `milepost index [--rebuild]` | Build or update the local search index |
| `milepost search QUERY [--k N] [--json]` | Search the notes: keyword, plus meaning-based when the `search` extra is installed |
| `milepost outline PATH [--json]` | Symbols, signatures and line ranges of one file, computed now (Python, TypeScript, JavaScript). Works in any git repository, no setup |
| `milepost impact PATH [--json]` | Files that import a file and the tests likely to cover it, computed now. A static import graph. Works with no `milepost.toml` |
| `milepost sync [--base REF] [--json]` | What changed and which notes to update, and how. With no `milepost.toml` it lists the changed files only |
| `milepost status [--json]` | Per module: who reviewed its note, and how many lines, commits and agent-authored commits have changed since. Never-reviewed modules first |
| `milepost report --base REF [--format markdown\|json]` | A review aid for a change range. Always exits 0 |
| `milepost uninstall [--delete-notes] [--yes]` | Remove what `init` added. Lists first; changes nothing without `--yes`. See [Remove Milepost](#remove-milepost) |
| `milepost hooks install\|uninstall` | Manage the git hooks and the merge driver. Never overwrites a hook it did not write |
| `milepost doctor [--json]` | Report the environment milepost needs. Exit 3 when a drafting variable is missing |
| `milepost serve` | Run the MCP server on stdio. Started by the plugin, not by hand |
| `milepost hook session-start\|post-edit\|stop` | Called by the plugin hooks, with JSON on stdin. Always exit 0 |
| `milepost merge-driver` | Git merge driver for note files. Called by git, not by you |

The git hooks `hooks install` adds are `post-merge` and `post-checkout` (run `index`, never block) and `pre-commit` (runs `check --no-churn`, which blocks on failures; bypass with `git commit --no-verify`).

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | The check or operation found failures |
| 2 | Usage or configuration error |
| 3 | Environment error (missing dependency or variable, no search index, unreadable repository) |

---

## What `check` reports

| Finding | Severity | Meaning |
|---|---|---|
| `STALE_NOTE` | warning (failure if `[check] stale = "fail"`) | A file the note covers changed after the note was last touched. In CI mode: the pull request edits covered code and does not touch the note |
| `INDEX_OBSOLETE` | warning | A `kb/INDEX.md` from an older version is still in the repository. The index is no longer stored; delete the file |
| `NOTE_INVALID`, `MISSING_KEY`, `INVALID_STATUS`, `ID_PATH_MISMATCH`, ... | failure | A note's frontmatter is missing or wrong |
| `MISSING_NOTE` | warning | A declared module has no note yet |
| `UNCOVERED_DIR` | warning | A source directory is covered by no module |
| A note says "Files withheld" | The credential scan found something shaped like a key or password in those files (often a constant such as a token type) and left only them out. Read the file; if it is safe, add it to `[draft] secret_scan_allow` in `milepost.toml` and redraft. (`draft.exclude` still wins: a path matching `**/*secret*` is never read, allow-listed or not.) Until then the note says it does not describe them |
| `CITATION_BROKEN` | warning | A note cites (in backticks, in Entry points, File map, Invariants or Gotchas) a file that is not in the repository, or a `file::symbol` whose name does not appear in the file. Lenient on purpose: it flags only what is clearly absent |
| `UNREVIEWED_CHURN` | warning | A reviewed note's source files changed by more than `visibility.churn_warn_lines` since the review. Never a failure |

**CI mode** (`milepost check --ci --base origin/main`) judges a pull request by what it changes. A pull request that edits code a note covers, without touching that note, gets a `STALE_NOTE` finding (a failure only if `[check] stale = "fail"`, otherwise a warning). Stale notes the pull request doesn't touch are old debt and stay warnings. A new source directory with no module also fails. With `fail_on = "none"` in the config, the exit status is `0` regardless (report only).

---

## Configuration

`milepost.toml` lives at the repository root and is committed. [templates/milepost.toml.example](templates/milepost.toml.example) is a commented starting point.

| Section | Purpose |
|---|---|
| `[project]` | Project name and the notes folder (default `kb`) |
| `[modules.<id>]` | One table per module: `sources` (file globs, relative to the repo root), optional `title`, `related`, and `verify` (commands that check the module, shown to agents; write them yourself) |
| `[structure]` | `languages`, `ignore` globs, and `roots` where module candidates are looked for |
| `[index]` | Search index location and the embedding model and its dimension (these must agree) |
| `[draft]` | drafting limits (`max_source_bytes`, default 60000 per module, about 15,000 tokens; larger modules are partly read as outlines and the note says so), files that are never read (`**/.env*`, keys, credentials), and `secret_scan_allow` (globs of files the credential scan withheld that you have checked and want included) |
| `[check]` | `stale` (`warn`, the default, or `fail`: a pull request that edits covered code without touching its note fails) and `fail_on` (`stale`, the default, or `none` for report-only) |
| `[visibility]` | `agent_trailers` (regexes that mark a commit as agent-authored; default: Claude Code's `Co-Authored-By ... noreply@anthropic.com` trailer and its "Generated with Claude Code" line) and `churn_warn_lines` (default 1000) |

A `milepost.toml` written by an earlier version has `max_source_bytes = 200000` written out; change it to `60000` to read less per module (the notes say which files were read as outlines only).

Module ids are lowercase letters, digits, `_` and `-`. Globs must be relative and must not contain `..`. Invalid configuration is reported with the exact field path and exits with status 2.

## Environment variables

| Variable | Purpose |
|---|---|
| `MILEPOST_DISABLED` | Set to `1` to pause Milepost: see [Pause Milepost](#pause-milepost) |

Nothing else is read from the environment: Claude writes the notes, so there are no model names or keys to configure. (Earlier versions could draft with a separate model through `MILEPOST_MODEL`; that was removed. A `milepost.toml` that still has `mode` or `provider_model` under `[draft]` keeps working, and the settings are ignored; `mode = "model"` is ignored too; `milepost doctor` warns and says to delete the line.)

## Fewer permission prompts

The plugin's `/milepost:kb-init` command and its `kb-usage` skill pre-approve the Milepost tools while they run, so setup and the normal work loop do not stop to ask for each call. Outside them, Claude Code asks the first time it calls a Milepost tool. To stop that everywhere, allow the server once in your own settings (`~/.claude/settings.json`, or `.claude/settings.json` in a repository):

```json
{ "permissions": { "allow": ["mcp__plugin_milepost_milepost__*"] } }
```

A plugin cannot ship permission rules itself, so this one line is yours to add. `kb_update` writes only note files under `kb/`, saved as drafts; nothing is reviewed until a person says so.

## Troubleshooting

Start with `milepost doctor`. It checks Python, git, SQLite, the config file, the optional search extra and your git hooks, and says what is missing.

| Symptom | Likely cause and fix |
|---|---|
| `milepost: command not found` right after `uv tool install` | uv put the command in a folder that is not on your PATH. Run `uv tool update-shell` and open a new terminal (or add the folder uv printed to PATH) |
| `/mcp` does not list `milepost` | Claude Code was not started with `--plugin-dir ~/milepost/plugin`, or `uv sync` was not run in the milepost checkout. Run `claude plugin validate ~/milepost/plugin` |
| Hooks seem to do nothing | They fail open on purpose. Run one by hand: `echo '{}' \| uv run --project ~/milepost milepost hook session-start`, and read stderr |
| `config file not found` | You are outside a repository with a `milepost.toml`. Run `/milepost:kb-init` or `milepost init`, or pass `--repo` |
| `STALE_NOTE` after an ordinary edit | Expected: any commit that touches a covered file after the note was last touched counts, comments included. Re-read the code and touch the note (`kb_update`, or edit it; an unchanged body is fine if it still holds). It only warns unless you set `[check] stale = "fail"` |
| `milepost review` refuses | The note is stale: update it first (any edit counts as touching it), then review |
| `CITATION_BROKEN` | The note names a file or symbol that isn't there. Fix the note: it may be an invented detail |
| CI fails at "Install milepost" | milepost isn't on PyPI yet. Edit `.github/workflows/milepost.yml` to install from a git URL |
| The first search is slow | With the `search` extra it is downloading the embedding model (about 130 MB) once |
| A commit is blocked by `pre-commit` | A note is stale or invalid. Fix it, or `git commit --no-verify` |

---

## Remove Milepost

```bash
milepost uninstall                 # lists what it would remove; changes nothing
milepost uninstall --yes           # removes it, keeps your notes
milepost uninstall --delete-notes --yes   # also deletes the notes under kb/
```

It removes only what milepost wrote: the git hooks and the merge driver config, the milepost line in `.gitattributes` and the `kb/` lines in `.gitignore` , the CI workflow if you have not edited it, the search index, and `milepost.toml`. The notes are plain markdown and are kept unless you pass `--delete-notes`; with that flag it refuses, and changes nothing, while `kb/` has uncommitted changes.

It never edits files you own. It lists them instead, under "by hand": the milepost section in `CLAUDE.md` or `AGENTS.md`, CODEOWNERS lines for `kb/`, entries in your own hook manager, `MILEPOST_*` lines that older versions left in `.env`, and the `--plugin-dir` flag. It does not touch git history. Nothing is committed for you: review with `git status`, commit the removal, and `git restore .` or a revert brings tracked files back. The tool itself is removed with `uv tool uninstall milepost`.

---

## What is not built yet

- **Installing the plugin from a marketplace**, `uvx milepost`, and a working generated CI workflow: all need a published release.
- **Other agents:** the MCP server is standard and `templates/AGENTS.md.snippet` carries the playbook, but only Claude Code has been considered and nothing has been tested with another agent.
- **Windows:** untested.
- **Measurement:** whether any of this saves tokens or helps reviewers is untested. See [PILOT.md](PILOT.md).
