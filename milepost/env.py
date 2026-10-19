"""The pause switch: MILEPOST_DISABLED (see USAGE.md)."""

import os
from collections.abc import Mapping

DISABLED_VAR = "MILEPOST_DISABLED"
_TRUTHY = {"1", "true", "yes", "on"}


def is_disabled(environ: Mapping[str, str] | None = None) -> bool:
    """True when MILEPOST_DISABLED is set to 1, true, yes or on (the pause switch). The plugin
    hooks, the MCP server and the git hooks then do nothing; explicit CLI commands still run."""
    source = os.environ if environ is None else environ
    return source.get(DISABLED_VAR, "").strip().lower() in _TRUTHY
