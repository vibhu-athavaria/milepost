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
