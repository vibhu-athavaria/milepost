---
description: Set up the milepost knowledge base in this repository, or add new modules to it
---

Set up milepost in this repository. Follow these steps in order and stop where a step says to.

In this plugin, run milepost like this (call it `MILEPOST` below):

`uv run --quiet --project "${CLAUDE_PLUGIN_ROOT}/.." milepost`

If a plain `milepost` command is on the PATH, you may use that instead.

1. Run `MILEPOST doctor --json`. It exits non-zero when something is missing, so read its output anyway and fix or report anything marked `fail`. By default notes are written in **agent mode**: you write them yourself with this session's model, so no key is needed (this uses tokens in this session). Only if the user asks for a separate, cheaper model, check that `MILEPOST_MODEL`, the provider key and the `model` extra are set up (doctor says what is missing) and add `--model-mode` to the `init` commands below.
2. Run `MILEPOST scan --json` to list the candidate modules that are not yet declared. If there are none, say so and stop.
3. Run `MILEPOST init --dry-run --modules <all candidate ids, comma separated>`. Show the user the candidate modules, the files that would be sent to the drafting model, and the estimated token count. Ask once which modules to keep and wait for the answer. This is the only confirmation.
4. Run `MILEPOST init --yes --modules <the confirmed ids>` (plus `--model-mode` if chosen). It declares the modules, installs the git hooks and merge driver, writes the CI workflow, and builds the search index. In the default agent mode it writes no notes and lists the modules to draft; in model mode it drafts them itself. For the agent mode list, for each module: for each one, call `kb_draft_module`, write the note body from the packet it returns (follow its `system_prompt`, use only its sources, no frontmatter), and call `kb_update` with `read_hash` set to the packet's `source_hash_now`. Packets can be large (the dry-run in step 3 showed the token estimate), so draft one module at a time and, if the total is big, tell the user and suggest model mode or fewer modules.
5. Tell the user the one step that needs them: read each draft under `kb/modules/` and run `MILEPOST review module/<id>` for each one that is correct. Then commit `milepost.toml`, `kb/`, `.gitattributes`, and `.github/workflows/milepost.yml`.

Re-running this command is safe. It never overwrites an existing note or the existing config, and it only offers modules that are not yet declared.
