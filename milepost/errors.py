"""Exceptions shared across milepost. Exit codes follow SPEC section 8.1."""


class MilepostError(Exception):
    exit_code = 1


class InvalidConfig(MilepostError):
    exit_code = 2

    def __init__(self, field_path: str, message: str) -> None:
        self.field_path = field_path
        self.message = message
        super().__init__(f"{field_path}: {message}" if field_path else message)


class UsageError(MilepostError):
    """Bad command-line usage or an unusable input (exit 2)."""

    exit_code = 2


class NoteInvalid(MilepostError):
    """A note's frontmatter is missing or cannot be parsed."""


class ConfigNotFound(MilepostError):
    exit_code = 2

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"config file not found: {path}")


class IndexRebuildRequired(MilepostError):
    """The index was built with a different embedding model or dimension."""

    exit_code = 1


class IndexMissing(MilepostError):
    """There is no search index yet."""

    exit_code = 3


class EnvironmentProblem(MilepostError):
    """Something the environment must provide is missing: a variable, a tool, a git repository."""

    exit_code = 3


class ProviderError(MilepostError):
    """The LLM provider failed, or drafting cannot safely proceed (exit 4)."""

    exit_code = 4


class SecretDetected(ProviderError):
    """Source sent for drafting contains something that looks like a credential."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"possible secret in {path}; nothing was sent for this module")
