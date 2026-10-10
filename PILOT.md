# Pilot: does milepost reduce agent effort on Kaihle?

Status: baseline recorded (TASKS M5a). The with-milepost run happens in M11. The go/no-go decision is written here after that run.

## What is being measured

Five Kaihle sub-agent runs made without milepost. Each run is one Claude Code sub-agent log. The numbers come from `scripts/pilot_usage.py`, which reads the logs under `~/.claude/projects/`.

Headline metric: `fresh_after_first`, the fresh input tokens (input plus cache creation) after the first turn. Every agent starts with a fixed context of about 58k tokens (system prompt, tools, CLAUDE.md), which `floor` shows and the headline metric excludes. Secondary metrics: turns, tool calls, and active time.

## Baseline (no milepost)

| Task | Agent | Base commit | floor | fresh_after_first | fresh_total | cache_read | turns | tool calls | active |
|---|---|---|---|---|---|---|---|---|---|
| T9 DeepEval harness slice 1 | af58bbb4 | b5879dd | 57,972 | 195,289 | 253,261 | 4,098,435 | 39 | 48 | 12:12 |
| T15 quiz context fix slice 1 | a4723f09 | b5879dd | 58,223 | 28,568 | 86,791 | 1,068,901 | 15 | 20 | 3:48 |
| T9 slice 3 judge adapter | a0524274 | 4d44e0d | 59,306 | 53,269 | 112,575 | 1,789,474 | 19 | 23 | 3:29 |
| T15 slice 2 quiz wiring | a1c42b1b | 4d44e0d | 59,031 | 60,468 | 119,499 | 2,328,848 | 24 | 35 | 6:52 |
| Fix quiz task CRITICAL log error | a01d65a7 | 4d44e0d (best effort) | 58,464 | 6,727 | 65,191 | 311,797 | 6 | 5 | 0:43 |

All five ran on `claude-sonnet-5-5`. Raw data: `pilot/baseline.json`. Task metadata: `pilot/tasks.json`.

## What is frozen

- **Prompts.** Each task is the exact prompt its parent agent gave the sub-agent. They contain private Kaihle plans, so they are stored locally in `pilot/prompts/<agent-id>.md` (git-ignored) and `pilot/tasks.json` records the SHA-256 of each. A rerun must use the same file; check the hash first.
- **Starting code.** Each task starts from the base commit in the table. For the first four, the commit is where the agent's worktree branch was created. The last task did not use a worktree, so its base is the best match for the start time and may not be exact.
- **Settings.** Same model, same Claude Code version, same MCP servers. The baseline logs do not record whether ByteRover was available to these sub-agents. Confirm that before the M11 run and keep it identical.

## Known limitations

- **These are implementation slices, not exploration tasks.** The parent hands each sub-agent a detailed plan, and the runs make only 0 to 3 Read calls. milepost saves searching, so there may be little for it to save here. A small effect on this benchmark would not prove milepost is useless.
- **One run per task.** Agents vary run to run. The five tasks differ about 29-fold on `fresh_after_first` (6.7k to 195k), so the smallest tasks will be noisy.
- **Output tokens are not compared.** The logged values look undercounted.
- **Reads through Bash are not counted.** Tool-call count is used instead.
- **Outcomes are not yet recorded.** The pass/fail criterion for each task has to be written down before the M11 run (see below).

## To fill in before M11

- [ ] For each task, what counted as done (tests pass, review accepted, merged). Not recorded yet.
- [ ] Whether ByteRover was available to these sub-agents, and whether it will be during the M11 run.
- [ ] Decision rule. Proposed, not agreed: milepost passes if the total `fresh_after_first` across the five tasks is at least 30% lower, with no task failing that passed in the baseline.

## How to rerun (M11)

1. In a Kaihle checkout at each task's base commit, with the milepost notes for that commit in place, start a sub-agent with the saved prompt.
2. `python scripts/pilot_usage.py --project /Users/vibhu/Projects/kaihle --last 5` prints the same table for the new runs.
3. Compare per task and in total. Add the new table and the decision below.

## Decision

Not made yet.
