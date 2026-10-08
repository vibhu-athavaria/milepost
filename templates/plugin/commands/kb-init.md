---
description: Set up the kbmap knowledge base in this repository, or add new modules to it
---

Set up kbmap in this repository. Follow these steps in order and stop where a step says to.

1. Run `kbmap doctor --json`. If `KBMAP_MODEL` or the provider key variable is missing, tell the user exactly which environment variables to set, then stop. Do not continue without them.
2. Run `kbmap scan --json` to list the candidate modules that are not yet declared. If there are none, say so and stop.
3. Run `kbmap init --dry-run --modules <all candidate ids>`. Show the user the candidate modules, the files that would be sent to the drafting model, and the estimated token count. Ask once which modules to keep and wait for the answer. This is the only confirmation.
4. Run `kbmap init --yes --modules <the confirmed ids>`. It declares the modules, installs the hooks and merge driver, writes the CI workflow, drafts the module notes, and builds the index.
5. Tell the user the one step that needs them: read each draft under `kb/modules/` and run `kbmap review <id>` for each one that is correct. Then commit `kbmap.toml`, `kb/`, `.gitattributes`, and `.github/workflows/kbmap.yml`.

Re-running this command is safe. It never overwrites an existing note or the existing config, and it only offers modules that are not yet declared.
