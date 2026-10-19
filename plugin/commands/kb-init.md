---
description: Set up the milepost knowledge base in this repository, or add new modules to it
allowed-tools: Bash(uv run --quiet --project * milepost doctor*), Bash(uv run --quiet --project * milepost scan*), Bash(uv run --quiet --project * milepost init*), Bash(milepost doctor*), Bash(milepost scan*), Bash(milepost init*), mcp__plugin_milepost_milepost__kb_overview, mcp__plugin_milepost_milepost__kb_module, mcp__plugin_milepost_milepost__kb_file, mcp__plugin_milepost_milepost__kb_search, mcp__plugin_milepost_milepost__kb_outline, mcp__plugin_milepost_milepost__kb_impact, mcp__plugin_milepost_milepost__kb_sync, mcp__plugin_milepost_milepost__kb_check, mcp__plugin_milepost_milepost__kb_draft_module, mcp__plugin_milepost_milepost__kb_update
---

Set up milepost in this repository. Follow these steps in order and stop where a step says to.

In this plugin, run milepost like this (call it `MILEPOST` below):

`uv run --quiet --project "${CLAUDE_PLUGIN_ROOT}/.." milepost`

If a plain `milepost` command is on the PATH, you may use that instead.

1. Run `MILEPOST doctor --json`. It exits non-zero when something is missing, so read its output anyway and fix or report anything marked `fail`. You write the notes yourself in this session, so no key or model setup is needed (this uses tokens in this session).
2. Run `MILEPOST scan --json` to list the candidate modules that are not yet declared. If there are none, say so and stop.
3. Run `MILEPOST init --dry-run --modules <all candidate ids, comma separated>`. Show the user the candidate modules, the files you would read to write the notes, and the estimated token count. Ask once which modules to keep and wait for the answer. This is the only confirmation.
4. Run `MILEPOST init --yes --modules <the confirmed ids>`. It declares the modules, installs the git hooks and merge driver, writes the CI workflow, and builds the search index. It writes no notes itself and lists the modules to draft. For each one, call `kb_draft_module` (a large module comes in parts: call it again with `part=2`, `3`, ... until you have read them all), write the note body from what it returns (follow its `system_prompt`, use only its sources, no frontmatter; if it lists `withheld` files, start the body with its `truncation_notice`), and call `kb_update` with `read_hash` set to its `source_hash_now`. The sources can be large (the dry run in step 3 showed the token estimate), so draft one module at a time and, if the total is big, tell the user and suggest fewer modules.
5. Tell the user the one step that needs them: read each draft under `kb/modules/` and run `MILEPOST review module/<id>` for each one that is correct. Then commit `milepost.toml`, `kb/`, `.gitignore`, `.gitattributes`, and `.github/workflows/milepost.yml`.

Re-running this command is safe. It never overwrites an existing note or the existing config, and it only offers modules that are not yet declared.
