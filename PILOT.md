# Measuring whether Milepost helps

Milepost's central claims are untested: that agents using the notes read fewer files and spend fewer tokens, and that developers keep a better grip on agent-written code. This page is the protocol for testing them on a repository you own. It holds no results; keep your own baseline data, prompts and logs outside this repository, because task prompts often contain private plans.

## What to measure

Per task, from Claude Code's session logs (`scripts/pilot_usage.py` reads them):

| Metric | Meaning |
|---|---|
| `fresh_after_first` | Fresh input tokens (input plus cache creation) after the first turn. The headline metric: every agent starts with a fixed context of about 58k tokens (system prompt, tools, `CLAUDE.md`), which `floor` shows and this metric excludes |
| turns, tool calls | How much the agent worked |
| active time | Time spent, excluding waiting for a person |
| outcome | Did the task meet its done criteria (tests pass, review accepted) |

Output tokens are not compared (the logged values look undercounted), and file reads made through a shell command are not counted, so tool-call count stands in for them.

## Protocol

1. **Pick five tasks** that represent your work: a feature, a bug fix, a cross-module change, a question about existing behavior, a refactor. Write each as a fixed prompt and record, before any run, what counts as done.
2. **Baseline (no Milepost).** Run each task from a recorded base commit. Record the metrics above. Note the model, the Claude Code version and which MCP servers were available.
3. **With Milepost.** Run `/milepost:kb-init` on the repository, review every note, then run the same prompts from the same base commits with the plugin loaded and the same model and settings.
4. **Review effort** (the second claim). Take three agent-written pull requests. Someone who did not write them writes five factual questions each from the code diff (what behavior changed, which module, which invariant is touched). One reviewer answers using only the note diff and `milepost report`, timed; another answers from the code diff alone. Compare correct answers and time. (`milepost report` is not built yet; until then use the note diff alone.)
5. **Tool use.** Record which `kb_*` tools the agent actually called per run. A tool that was never called saves nothing.
6. **Decide before you look.** Write the pass rule down before the second run.

A rule to start from, not agreed: Milepost passes if the total `fresh_after_first` across the five tasks is at least 30% lower, no task that passed in the baseline fails, and the review-effort comparison gives at least 80% as many correct answers in at most half the time.

## Known limits of this design

- Implementation tasks that arrive with a detailed plan involve almost no searching, so Milepost has little to save there. A small effect on such a benchmark does not show it is useless; include exploration and question tasks.
- One run per task. Agents vary run to run, and tasks differ by an order of magnitude in size, so the smallest are noisy. Repeat if you can.
- A good `CLAUDE.md` captures much of the benefit on a small repository; expect the difference to show on larger ones.
- Outcomes need written done criteria, or "no regression" cannot be judged.

## Running the usage script

```bash
python scripts/pilot_usage.py --project /path/to/your/repo --last 5
python scripts/pilot_usage.py --project /path/to/your/repo --kind sessions --format csv
python scripts/pilot_usage.py path/to/agent-abc.jsonl path/to/agent-def.jsonl
```
