import asyncio
import json
import re
import shlex
from importlib.metadata import version
from pathlib import Path

import yaml
from typer.testing import CliRunner

from milepost.cli import app
from milepost.mcp_server import build_server

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugin"
runner = CliRunner()
TOOL_NAME = re.compile(r"\bkb_[a-z_]+\b")


def tool_names() -> set[str]:
    server = build_server(ROOT)
    return {tool.name for tool in asyncio.run(server.list_tools())}


def frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text()
    assert text.startswith("---\n")
    loaded = yaml.safe_load(text.split("---\n")[1])
    assert isinstance(loaded, dict)
    return loaded


def test_plugin_manifest_when_parsed_then_has_name_version_and_description() -> None:
    manifest = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())

    assert manifest["name"] == "milepost"
    assert manifest["version"] == version("milepost")
    assert manifest["description"]


def test_plugin_mcp_config_when_parsed_then_starts_milepost_serve() -> None:
    config = json.loads((PLUGIN / ".mcp.json").read_text())

    server = config["mcpServers"]["milepost"]
    assert server["args"][-2:] == ["milepost", "serve"]
    assert "${CLAUDE_PLUGIN_ROOT}" in " ".join(server["args"])


def test_plugin_skill_when_present_then_frontmatter_has_name_and_description() -> None:
    meta = frontmatter(PLUGIN / "skills/kb-usage/SKILL.md")

    assert meta["name"] == "kb-usage" and meta["description"]


def test_plugin_commands_when_listed_then_only_kb_init_present() -> None:
    assert sorted(p.name for p in (PLUGIN / "commands").iterdir()) == ["kb-init.md"]


def test_plugin_kb_init_command_when_parsed_then_names_doctor_scan_and_init_steps_in_order() -> (
    None
):
    text = (PLUGIN / "commands/kb-init.md").read_text()
    assert frontmatter(PLUGIN / "commands/kb-init.md")["description"]

    positions = [
        text.index(f"MILEPOST {step}")
        for step in ("doctor", "scan", "init --dry-run", "init --yes")
    ]

    assert positions == sorted(positions)


def test_plugin_commands_when_cli_subcommands_referenced_then_each_exists() -> None:
    text = (PLUGIN / "commands/kb-init.md").read_text()
    for command in set(re.findall(r"MILEPOST ([a-z-]+)", text)):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, command


def test_plugin_hooks_when_parsed_then_session_start_post_edit_and_stop_hooks_present() -> None:
    hooks = json.loads((PLUGIN / "hooks/hooks.json").read_text())["hooks"]

    assert set(hooks) == {"SessionStart", "PostToolUse", "Stop"}
    assert hooks["PostToolUse"][0]["matcher"] == "Edit|Write|MultiEdit"


def test_plugin_hooks_when_parsed_then_each_command_is_a_real_milepost_hook() -> None:
    hooks = json.loads((PLUGIN / "hooks/hooks.json").read_text())["hooks"]
    seen = set()
    for groups in hooks.values():
        for group in groups:
            for handler in group["hooks"]:
                words = shlex.split(handler["command"])
                assert words[-3:-1] == ["milepost", "hook"], handler["command"]
                assert "${CLAUDE_PLUGIN_ROOT}" in handler["command"]
                result = runner.invoke(app, ["hook", words[-1], "--help"])
                assert result.exit_code == 0, words[-1]
                seen.add(words[-1])
    assert seen == {"session-start", "post-edit", "stop"}


def test_playbook_when_skill_names_kb_tools_then_every_name_exists_in_mcp_server() -> None:
    known = tool_names()
    for path in (
        PLUGIN / "skills/kb-usage/SKILL.md",
        ROOT / "templates/CLAUDE.md.snippet",
        ROOT / "templates/AGENTS.md.snippet",
        PLUGIN / "commands/kb-init.md",
    ):
        named = set(TOOL_NAME.findall(path.read_text())) - {"kb_schema"}  # a frontmatter key
        assert named <= known, f"{path.name}: {sorted(named - known)}"


def test_playbook_when_spec_scenarios_listed_then_each_has_a_section_in_skill() -> None:
    skill = (PLUGIN / "skills/kb-usage/SKILL.md").read_text()
    headings = {
        "Start a task": "### Starting a task",
        "Note is `draft`": "### A note is `draft` or stale",
        "Note is stale": "### A note is `draft` or stale",
        "Change an existing file": "### Changing an existing file",
        "Add a file to an existing module": "### Adding a file to an existing module",
        "Rename or delete a file": "### Renaming or deleting a file",
        "Learned a gotcha or invariant": "### You learned a gotcha or invariant",
        "New module": "### A new module",
        "Code no module covers": "### Code that no note covers",
        "Hash is `CONFLICT`": "### A `CONFLICT` hash",
        "Before commit": "### Before you commit",
        "Finish a task": "### Finishing a task",
    }
    spec = (ROOT / "SPEC.md").read_text()
    table = spec[spec.index("### 12.5 Agent playbook") : spec.index("Token rule that applies")]
    scenarios = [
        row.split("|")[2].strip() for row in table.splitlines() if re.match(r"\| \d+ \|", row)
    ]

    assert len(scenarios) == 12
    for scenario in scenarios:
        assert headings[scenario] in skill, scenario


def test_agents_snippet_when_present_then_matches_claude_snippet_apart_from_the_intro() -> None:
    claude = (ROOT / "templates/CLAUDE.md.snippet").read_text().split("\n", 3)[3]
    agents = (ROOT / "templates/AGENTS.md.snippet").read_text().split("\n", 3)[3]

    assert claude.split("Before a task:")[1] == agents.split("Before a task:")[1]
