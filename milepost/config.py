"""Configuration loaded from milepost.toml (SPEC section 3)."""

import os
import re
import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from milepost.errors import ConfigNotFound, InvalidConfig

ModuleId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]*$")]


def _relative_glob(value: str) -> str:
    if value.startswith("/"):
        raise ValueError("must be relative to the repo root (no leading '/')")
    if ".." in Path(value).parts:
        raise ValueError("must not contain '..'")
    return value


RelativeGlob = Annotated[str, AfterValidator(_relative_glob)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Project(_Model):
    name: str
    kb_dir: str = "kb"

    @field_validator("kb_dir")
    @classmethod
    def _normalise_kb_dir(cls, value: str) -> str:
        """`kb/`, `./kb` and `kb` all mean the same folder; keep one spelling."""
        cleaned = os.path.normpath(value).replace(os.sep, "/")
        if cleaned in (".", "") or cleaned.startswith(("/", "..")):
            raise ValueError("must be a folder inside the repository, for example 'kb'")
        return cleaned


class Module(_Model):
    sources: Annotated[list[RelativeGlob], Field(min_length=1)]
    related: list[str] = []
    title: str | None = None
    verify: list[str] = []


class Structure(_Model):
    languages: list[str] = ["python"]
    ignore: list[str] = ["**/node_modules/**", "**/__pycache__/**", "**/.venv/**"]
    roots: list[RelativeGlob] = ["src", "app", "backend/app", "packages", "apps"]


class Index(_Model):
    backend: Literal["sqlite"] = "sqlite"
    path: str = "kb/.index/index.sqlite"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: PositiveInt = 384


LEGACY_DRAFT_KEYS = ("mode", "provider_model")


class Draft(_Model):
    max_source_bytes: PositiveInt = 200000
    exclude: list[str] = ["**/.env*", "**/*secret*", "**/*.pem", "**/*.key", "**/credentials*"]
    # Files the credential scan would withhold from drafting but a person has checked are safe.
    secret_scan_allow: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _legacy_keys(cls, data: object) -> object:
        """Configs written by earlier versions carry `mode` and `provider_model`; they are
        accepted and ignored (drafting with a separate model was removed), so an upgrade never
        locks a repository out of its own commands. `milepost doctor` points at them."""
        if not isinstance(data, dict):
            return data
        return {k: v for k, v in data.items() if k not in LEGACY_DRAFT_KEYS}


class Check(_Model):
    fail_on: Literal["stale", "none"] = "stale"
    # "warn" (default): a stale note is reported but never fails a check or a pull request.
    # "fail": a pull request that edits covered code without touching its note fails.
    stale: Literal["warn", "fail"] = "warn"


def _valid_regex(value: str) -> str:
    try:
        re.compile(value)
    except re.error as error:
        raise ValueError(f"not a valid regular expression: {error}") from error
    return value


class Visibility(_Model):
    agent_trailers: list[Annotated[str, AfterValidator(_valid_regex)]] = [
        r"(?im)^Co-Authored-By:.*noreply@anthropic\.com",
        r"Generated with \[?Claude Code",
    ]
    churn_warn_lines: NonNegativeInt = 1000


class Config(_Model):
    project: Project
    modules: dict[ModuleId, Module] = {}
    structure: Structure = Structure()
    index: Index = Index()
    draft: Draft = Draft()
    check: Check = Check()
    visibility: Visibility = Visibility()

    @model_validator(mode="after")
    def _default_titles(self) -> "Config":
        for module_id, module in self.modules.items():
            if module.title is None:
                module.title = module_id
        return self


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise ConfigNotFound(str(path))
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise InvalidConfig("", f"invalid TOML: {error}") from error
    try:
        config = Config.model_validate(raw)
    except ValidationError as error:
        first = error.errors()[0]
        raise InvalidConfig(".".join(str(part) for part in first["loc"]), first["msg"]) from error
    for module_id, module in config.modules.items():
        for related in module.related:
            if related not in config.modules:
                raise InvalidConfig(
                    f"modules.{module_id}.related",
                    f"'{related}' is not a declared module",
                )
    return config


def load_config_or_default(path: Path) -> Config:
    """The config at `path`, or defaults when there is no milepost.toml, so the computed tools
    (outline, impact, sync) work in any git repository with no setup. An existing but invalid
    file is still an error."""
    if path.exists() or path.is_symlink():
        return load_config(path)
    return Config(project=Project(name=path.resolve().parent.name))
