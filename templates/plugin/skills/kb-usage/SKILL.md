---
name: kb-usage
description: Use the milepost knowledge base to find the right modules and files before searching code, and to write back what was learned after a task. Follow the scenario steps so the right kb tool is called at the right time.
---

# Using the codebase knowledge base

Use this skill when a repository has a `kb/` folder and `milepost` tools are available.

Notes are levels: L1 index, L2 module note, L3 file note, L4 passage note. Only L2 and L3 notes carry `sources` and a `source_hash`, so only they can go stale.

Each tool response includes `next_steps`. Follow them. The scenarios below are derived from the playbook in SPEC section 12.5.

## Scenarios

Find the scenario that matches what you are doing and follow its steps in order.

### Starting a task

1. Call `kb_overview`. Pick the module that owns the work. If the stale count is above zero, note which notes are stale.
2. Call `kb_module` with that id. Read Invariants and Gotchas before touching code.
3. Call `kb_file` with each path you expect to touch. Use `kb_search` when the owning module is unclear. Do not grep the whole repository first.

### A note is `draft` or stale

- `draft`: its claims are unverified. Check them in the code and tell the user you relied on a draft note.
- Stale: do not trust it. Read the current source, then call `kb_update` with a corrected body.

`kb_module` and `kb_file` return `source_hash_now`. Pass it to `kb_update` as `read_hash` for L2 and L3 notes. If you get `STALE_READ`, the source changed after you read it: call `kb_module` or `kb_file` again, re-read the source, and retry.

### Changing an existing file

1. Read the current source of the file immediately before you change it.
2. Make the change.
3. Call `kb_file` with the path. It lists every L2 and L3 note that covers the file.
4. For each listed note, call `kb_update` with a small, factual revision. If the note is still accurate, say so to the user and still call `kb_update` after re-reading the source, so the hash is current.
5. Call `kb_check`. Fix every finding before you commit.

### Adding a file to an existing module

1. Call `kb_module` for the owning module and read the source of the new file.
2. If the module's purpose, entry points, owned data, or invariants changed, call `kb_update` on the L2 note.
3. Call `kb_check`.

### Renaming or deleting a file

1. Call `kb_file` with the old path before the change, and note every covering note.
2. After the change, call `kb_update` on each covering L2 note.
3. If `kb_check` reports `ORPHAN_NOTE` for an L3 note, tell the user. Do not delete it yourself.
4. Call `kb_check`.

### You learned a gotcha or invariant

- Add it to the L2 note's Gotchas or Invariants with `kb_update`, after reading the source it refers to.
- Write an L3 note only when one file has gotchas, invariants, or behavior that do not fit in the module note. Do not write an L3 for every file you touch.
- Use an L4 note only when the point is tied to one narrow passage.

### A new module

`kb_update` cannot create an L2 note. Do not try.

1. Add `[modules.<id>]` with `sources` to `milepost.toml`.
2. Call `kb_draft_module` with the id. It writes the note as `draft`. If it returns `ENVIRONMENT`, tell the user which variable to set.
3. Call `kb_check`.
4. Tell the user to read the note and run `milepost review <id>`. The note stays `draft` until they do.

### Code that no note covers

If `kb_check` reports `UNCOVERED_DIR`, or you find source that no module's `sources` covers, follow "A new module" if a module should exist. Otherwise ask the user. Do not widen a module's globs to absorb it without asking.

### A `CONFLICT` hash

Stop. Do not edit the note and do not run `milepost rehash`. Tell the user the note needs review and a `milepost rehash <id>` run.

### Before you commit

1. Call `kb_check`.
2. Fix every failure.
3. Never write a `KB-Waive` trailer yourself. Ask the user.

## Do not

- Edit `source_hash` by hand.
- Change `sources`, `id`, or `kb_schema` through `kb_update`.
- Write a note you have not read the source for. `kb_update` records the hash of whatever is on disk, so a note written without reading the code is stored as current when it is not.
- Rewrite a whole note when a small edit will do. Small edits reduce merge conflicts.
