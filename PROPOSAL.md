# Proposal: Agent-Driven Codebase Knowledge Base (Milepost)

Written for: maintainers and engineers who would decide whether to fund and build this.

## 1. Problem

Coding agents learn a repository by searching it. Each session they grep, open files, and guess which ones matter. This has four costs:

- **Context waste.** Files opened to find the right file are paid for in tokens and never used.
- **Missed code.** Agents that search by keyword miss the file that owns a behavior but doesn't share its name.
- **No continuity.** What an agent learned about why a module works the way it does is lost when the session ends. The next agent, or the same developer's next session, rediscovers it.
- **No shared memory across people.** Each developer's agent builds its own understanding, and none of it reaches the team.

Existing context tools are one attempt at this, and they can fail silently. In one team's measurement, a context-tree query tool failed on 22 of 27 queries over 30 days, and agents fell back to raw search without anyone noticing. That is the failure mode this proposal must design against: a knowledge base that is unreliable is worse than none, because agents trust it.

## 2. Existing solutions

| Tool | Derived code graph | Human-readable notes | Agent can write notes | Gap |
|---|---|---|---|---|
| codebase-memory-mcp | Yes (SQLite, auto-sync on file change) | No | Only ADRs (`manage_adr`) | No prose; export is binary |
| CodeSeeker | Yes (SQLite, manual sync) | No | No (read-only) | Directory summaries are averaged embeddings, not text |
| code-graph-mcp | Yes (AST, call graph) | No | Not verified | Returns compressed views by detail level |
| Basic Memory | No | Yes (markdown in git) | Yes | No code parsing |
| Context-tree tools (e.g. ByteRover) | No | Yes | Yes | Reliability issue above |

Sources: READMEs of codebase-memory-mcp and CodeSeeker, fetched and summarized by a small model (quotes are paraphrase); search snippets for the rest. Not verified: code-graph-mcp and Basic Memory beyond their summaries.

## 3. Why build rather than adopt

No reviewed tool combines a derived code graph with human-readable notes that the agent maintains through a write path. The structural layer is solved; we should depend on it, not rebuild it. The gap is the notes layer and the discipline that keeps notes honest.

Scope of what we build:
- a notes format and index,
- a staleness check tying each note to the source it describes,
- MCP tools for reading and writing notes,
- git integration for multi-developer use (section 6),
- initialization for existing repositories (section 11).

## 4. Who benefits and when it isn't worth it

Any repository large enough that agents spend meaningful context on search. Value scales with repo size, team size, and session count.

It is not worth it for small repos. A good `CLAUDE.md` plus a short architecture doc gets most of the benefit under a few hundred files. The first milestone is a measurement that decides whether to continue (section 7).

## 5. Design

**Four levels, like a book index:**

| Level | Name | Content | Written by |
|---|---|---|---|
| L1 | Index | One line per module, plus module dependency map | Generated from structure, prose reviewed |
| L2 | Module note | Purpose, entry points, owned data, invariants, related modules | Agent drafts, human reviews on first write |
| L3 | File note | Responsibilities, key symbols, gotchas | Agent, updated when the file changes |
| L4 | Passage note | Line-range notes for a specific behavior | Created on demand |

**Structure is derived, prose is written.** Imports, call paths, routes, and ownership come from the structural graph or a deterministic scan. Only prose (purpose, invariants, gotchas) is authored by an agent. Derived data can always be regenerated; prose is the part that can drift.

**Every prose note carries source hashes.** Frontmatter lists the source files a note describes and a hash of each. A check recomputes hashes and reports notes whose sources changed since the note was written. Drift is visible, not silent.

**Notes are files in git.** Markdown with frontmatter, one note per module or file, committed next to the code. The index (keyword and embedding search) is a local, rebuildable cache, git-ignored, never the source of truth.

**Agent read path:** L1 index → relevant L2 note → only the L3 notes or files those point to. The agent does not grep the whole repo first.

**Agent write path:** after a task, the agent updates each note whose source files it changed or whose behavior it learned. The write goes in the same commit as the code change.

**Interfaces:** MCP tools `kb_overview`, `kb_module`, `kb_file`, `kb_search`, `kb_update`, `kb_check`, `kb_draft_module`. Plus a CLI: `milepost check` (staleness), `milepost index` (rebuild local search index), `milepost init` (section 11), `milepost scan` (undeclared module candidates). Tool responses carry the next step, and plugin hooks remind the agent of covering notes when it edits a file and run the check before it finishes, so the read and write paths do not depend on the agent remembering them. SPEC section 12.5 holds the scenario-by-scenario steps.

**Language and tooling:** repository-agnostic. Hashing and frontmatter are language-neutral. Structure comes from an adapter, so any language with a structural graph works.

## 6. Multi-developer operation

This is the hardest part and the reason the design uses git as the transport.

**Constraint:** many developers commit, push branches, and merge to main many times a day. Each developer's local agent must see what others have merged, and notes must not be wrong about code on the branch being worked on.

**How changes propagate.** Notes are tracked files, so they travel with code through the normal path: push, PR, merge to main, `git pull` on each developer's machine. No separate sync service exists to run or fail. A developer's agent reads the working tree, so it sees exactly what their checked-out branch contains.

**Local refresh.** Two sources need refreshing after a pull or branch switch:
- the structural graph: codebase-memory-mcp auto-syncs on file change, so this is automatic per machine;
- the local search index: a `post-merge` and `post-checkout` git hook runs `milepost index`. It is a cache, so a missed run only makes search stale, never wrong about structure.

**Staleness is branch-local.** The hash check compares notes against the files in the working tree. A developer on a feature branch sees notes that match their branch's code, and sees a warning where their branch changed a file without updating its note.

**Merge conflicts.** Notes change less often than code, and one-file-per-module keeps conflicts local. Two additional mitigations:
- A custom git merge driver for the frontmatter hash field recomputes the hash after a merge, so a conflict only arises in prose, which needs a human decision anyway.
- Agents are instructed to make small, targeted note edits rather than rewriting whole notes, which reduces conflicts further.

**Who keeps main correct.** A CI check on every PR fails if a changed source file has a note whose hash no longer matches, unless the note was updated in the same PR. This is the only gate; it runs on each PR, so main stays consistent with its merges, not with some other branch's in-flight work.

**Concurrency under high merge frequency.** Because notes are per-module and updated with their code, two PRs touching different modules never conflict on notes. Two PRs touching the same module's note will conflict on prose, which surfaces a real disagreement about that module's documentation. That is acceptable at this scale; if it becomes frequent, the module note should be split.

**Risk:** a fast-moving team may update code without notes, and the CI gate becomes friction. Mitigation: the gate blocks only on changed files with an existing note, so a declared module without a note only warns, and an explicit waiver is recorded in the PR body. The one new-code gate is a new top-level source directory that no module covers: it fails in CI unless waived, so new code cannot appear without a decision about its note.

## 7. Plan and success criteria

1. **Baseline (go/no-go gate).** On a real repository, pick five representative tasks. Record files read and tokens used with no knowledge base. Done when recorded.
2. **Structural layer.** Install and verify the structural graph on the target repo, including auto-sync.
3. **Notes for the main modules.** Write L1 and L2 notes for the largest modules. Human review each.
4. **Staleness check.** Implement `milepost check`, run in pre-commit and CI.
5. **Agent integration.** MCP tools and a CLAUDE.md rule describing the read and write paths.
6. **Measurement.** Repeat the five baseline tasks. Success: fewer files read and fewer tokens, with no regression in task outcome. If not met, stop.
7. **Multi-developer pilot.** Run with two or three developers for two weeks. Measure merge conflicts on notes, stale-note warnings per PR, and whether agents on pulled main act on current notes.

Out of scope for v1: L4 notes everywhere, a hosted service, cross-repo search, and any database backend beyond local SQLite.

## 8. Storage, backends, and sync

**The notes are always in git.** They are the source of truth. Only the search index can live elsewhere, so storage is a deployment choice rather than a data-model choice.

**Index backends**, behind one storage interface:
- **Local:** SQLite (FTS5 keyword search plus exact vector search), per developer, git-ignored. Default, no setup.
- **Self-hosted:** Postgres with pgvector, shared by a team.
- **Cloud:** managed Postgres with pgvector, or a hosted vector store, using the same adapter contract.

**Configuration:** `milepost.toml` names the backend. Connection strings come from environment variables or a secrets manager, never from the repo.

**Updating on merge to main:** a GitHub Actions workflow triggered on `push` to `main` runs `milepost index` and writes to the configured backend. Trigger it directly on `push`, not by chaining off another workflow's completion. A shared database is then a cache that CI keeps current; each developer's local index is refreshed by a git hook after `pull`.

**Timing estimates (to be measured in the pilot):**

| Step | Estimate |
|---|---|
| Structural graph sync | Seconds for a typical repo |
| Note hash check and parse | Under a second for a few hundred notes |
| Embedding rebuild, local model, few hundred notes | Seconds to about a minute on CPU |
| Embedding rebuild, provider API | Seconds of network time, plus per-build cost |
| Full CI job, merge to shared DB updated | Roughly 2–5 minutes |
| Local refresh after `git pull` | Seconds |
| Search query, local SQLite | Milliseconds |
| Search query, remote Postgres | Tens to low hundreds of milliseconds, plus network |

A teammate's semantic search therefore lags main by about 2–5 minutes after merge. The notes an agent reads directly come from the checked-out working tree, so they are current for that branch; only semantic search lags.

**Recommendation:** start local-only with SQLite. Add shared Postgres in a later phase, once the pilot shows teammates need the same search results.

## 9. Open-source plan

Yes. The notes format, staleness check, git hooks, merge driver, and MCP tools are generic and can be one package. The package depends on an existing structural graph rather than reimplementing one.

Publish only after step 6 succeeds on a real repo. Until then the value is unproven, and publishing an unproven tool adds maintenance cost with no evidence of benefit.

## 10. Decisions needed

- Approve the baseline measurement (step 1) as the go/no-go gate.
- Confirm the repository to use for the pilot.
- Confirm the CI gate policy: block on stale notes for changed files with existing notes, with recorded waivers.
- Confirm local SQLite as the v1 backend.

## 11. Initializing an existing codebase

`milepost init` adds the knowledge base to a repo that already has code. It never overwrites existing files.

**1. Scaffold (no LLM, no network)**
- Creates `milepost.toml` with the local backend.
- Creates `kb/` and git-ignores the index path.
- Installs `post-merge` and `post-checkout` hooks.
- Adds a CI workflow template and prints a CLAUDE.md snippet for the team to paste. It does not edit CLAUDE.md itself.

**2. Structural scan (deterministic)**
- Runs the structural graph index: imports, routes, symbols.
- Proposes module boundaries from top-level directories and import clusters, written to `milepost.toml` as explicit entries. The proposal is a starting point; the config, not inference, defines what a module is.

**3. Draft notes (LLM, the only costly step)**
- For each configured module, generates an L2 note from the structure and a read of the source, with `status: draft`.
- Existing docs (README, architecture docs, CLAUDE.md) can seed the prose. Anything taken from them is marked "from docs, not verified against code."
- `--dry-run` reports module count and estimated token cost without writing anything.

**4. Human review**
- Agents treat `draft` notes as lower confidence and say so when relying on one.
- A reviewer sets `status: reviewed`. Only then is a note authoritative.

**5. Baseline and verify**
- Writes source hashes into each note's frontmatter so the staleness check starts clean.
- Runs `milepost check` and `milepost index`, then a sample search, and reports the result.

**Safety properties**
- **Idempotent:** re-running `init` skips existing notes and never overwrites a reviewed one.
- **Resumable:** on large repos, generation writes a progress file and continues from where it stopped.
- **Explicit:** modules can be declared by hand in `milepost.toml` for monorepos or unusual layouts, overriding the scan.

**Plugin entry point.** For plugin users, `/kb-init` is the one command. It checks the environment, shows the candidate modules and the cost once for confirmation, then runs the scaffold, drafting, hooks, CI workflow and index itself. The only step left to a person is reviewing the drafts. SPEC section 9.4 has the flow.
