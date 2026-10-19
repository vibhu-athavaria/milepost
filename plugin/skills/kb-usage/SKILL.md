---
name: kb-usage
allowed-tools: mcp__plugin_milepost_milepost__kb_overview, mcp__plugin_milepost_milepost__kb_module, mcp__plugin_milepost_milepost__kb_file, mcp__plugin_milepost_milepost__kb_search, mcp__plugin_milepost_milepost__kb_outline, mcp__plugin_milepost_milepost__kb_impact, mcp__plugin_milepost_milepost__kb_sync, mcp__plugin_milepost_milepost__kb_check, mcp__plugin_milepost_milepost__kb_draft_module, mcp__plugin_milepost_milepost__kb_update
description: Use the milepost knowledge base to find the right module, the exact symbols to read, the importers and tests before searching code, and to write back what changed after a task. Follow the scenario steps so the right kb tool is called at the right time.
---

# Using the codebase knowledge base

Use this skill when a repository has a `kb/` folder and `milepost` tools are available.

There is one note per module. The module index is built from the notes when you ask for it (`kb_overview`). A note is stale when code it covers changed after the note was last touched. Per-file detail is not a note: `kb_outline` computes it from the file each time.

Each tool response includes `next_steps`. Follow them. The scenarios below are derived from the playbook in SPEC section 12.5. Token rule for every scenario: prefer `kb_outline` plus a ranged read to reading a whole file, and one `kb_module` call to grepping a module.

## Scenarios

Find the scenario that matches what you are doing and follow its steps in order.

### Starting a task

1. Call `kb_overview`. Pick the module that owns the work. Note how many notes are stale.
2. Call `kb_module` with that id. Read Invariants and Gotchas before touching code. Note its `verify` commands.
3. Call `kb_outline` for each file you expect to read, then read only the line ranges you need.
4. Call `kb_impact` for each file you expect to change. It lists who imports it and which tests likely cover it.
5. Use `kb_search` only when the owning module is unclear. Do not grep the whole repository first.

### A note is `draft` or stale

- `draft`: its claims are unverified. Check them in the code and tell the user you relied on a draft note.
- Stale: do not trust it. Read the current source, then call `kb_update` with a corrected body.

`kb_module` returns `source_hash_now`. Pass it to `kb_update` as `read_hash`. If you get `STALE_READ`, the source changed after you read it: call `kb_module` again, re-read the source, and retry.

### Changing an existing file

1. Read the relevant lines of the file immediately before you change it.
2. Make the change.
3. Run the module's `verify` commands.
4. Call `kb_sync`. It lists every note that needs attention and what to update in it.
5. For each listed note, call `kb_update` with a small, factual revision. If the note is still accurate, still call `kb_update` with the unchanged body after re-reading the source: touching the note is how it stops being stale.
6. Call `kb_check`. Fix every finding before you commit.

### Adding a file to an existing module

1. Call `kb_module` for the owning module and read the new source.
2. Call `kb_sync`, then `kb_update` on the module note: add the file to the File map, and to Entry points if it is a new place to start.
3. Call `kb_check`.

### Renaming or deleting a file

1. Call `kb_impact` with the old path before the change, to see who imports it.
2. After the change, call `kb_sync` and `kb_update` on each covering module note.
3. Call `kb_check`.

### You learned a gotcha or invariant

- Add it to the module note's Gotchas or Invariants with `kb_update`, after reading the source it refers to. Cite the file in backticks, for example `` `routes/auth.py` ``. There are no per-file or per-passage notes; keep it in the module note.

### A new module

1. Add `[modules.<id>]` with `sources` to `milepost.toml`.
2. Call `kb_draft_module` with the id. It returns the instructions and the module's sources, in parts if the module is large (read every part: `part=1`, `2`, ...). Write the note body from them and save it with `kb_update` (`read_hash` = the `source_hash_now` it returned). If the response lists `withheld` files, put its `truncation_notice` at the top of the body.
3. Call `kb_check`.
4. Tell the user to read the note and run `milepost review <id>`. The note stays `draft` until they do.

### Code that no note covers

If `kb_check` reports `UNCOVERED_DIR`, or you find source that no module's `sources` covers, follow "A new module" if a module should exist. Otherwise ask the user. Do not widen a module's globs to absorb it without asking.

### A note with merge-conflict markers

If a note contains `<<<<<<<` markers, stop. Do not edit the note. Tell the user it needs a person to resolve the conflict.

### Before you commit

1. Call `kb_check`.
2. Fix every failure.
3. Never write a `KB-Waive` trailer yourself. Ask the user.

### Finishing a task

1. Call `kb_sync` and follow each route it lists with `kb_update`.
2. Run the `verify` commands it lists.
3. Tell the user which notes now show `draft` because you edited them, and that a person must run `milepost review <id>` for each. You cannot mark a note reviewed.
4. If `kb_sync` lists nothing, say so and stop.

## Do not

- Change `sources`, `id`, or `kb_schema` through `kb_update`.
- Write a note you have not read the source for. Touching a note clears its stale warning, so a note written without reading the code looks current when it is not.
- Rewrite a whole note when a small edit will do. Small edits reduce merge conflicts and are easier for a person to review.
