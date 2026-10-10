"""Configuration loaded from milepost.toml (SPEC section 3)."""

import re
import tomllib
from collections.abc import Mapping
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


class Module(_Model):
    sources: Annotated[list[RelativeGlob], Field(min_length=1)]
    related: list[str] = []
    title: str | None = None


class Structure(_Model):
    languages: list[str] = ["python"]
    ignore: list[str] = ["**/node_modules/**", "**/__pycache__/**", "**/.venv/**"]
    roots: list[RelativeGlob] = ["src", "app", "backend/app", "packages", "apps"]


class Index(_Model):
    backend: Literal["sqlite"] = "sqlite"
    path: str = "kb/.index/index.sqlite"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: PositiveInt = 384


class Draft(_Model):
    provider_model: str = "${MILEPOST_MODEL}"
    max_source_bytes: PositiveInt = 200000
    exclude: list[str] = [".env*", "**/*secret*", "**/*.pem", "**/*.key", "**/credentials*"]


class Check(_Model):
    fail_on: Literal["stale", "none"] = "stale"
    max_detail_notes: NonNegativeInt = 50


class Config(_Model):
    project: Project
    modules: dict[ModuleId, Module] = {}
    structure: Structure = Structure()
    index: Index = Index()
    draft: Draft = Draft()
    check: Check = Check()

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


_ENV_REFERENCE = re.compile(r"\$\{(\w+)\}")


def resolve_model(config: Config, env: Mapping[str, str]) -> str:
    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if not env.get(name):
            raise InvalidConfig("draft.provider_model", f"environment variable {name} is not set")
        return env[name]

    return _ENV_REFERENCE.sub(substitute, config.draft.provider_model)
