from pathlib import Path

import pytest

from milepost.config import Config, load_config, resolve_model
from milepost.errors import ConfigNotFound, EnvironmentProblem, InvalidConfig

FIXTURES = Path(__file__).parent.parent / "fixtures" / "config"

MINIMAL = """
[project]
name = "example"

[modules.services]
sources = ["app/services/**/*.py"]
"""


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "milepost.toml"
    path.write_text(text)
    return path


def test_load_config_when_valid_file_then_returns_models() -> None:
    config = load_config(FIXTURES / "valid.toml")

    assert config.project.name == "example"
    assert config.modules["services"].sources == ["backend/app/services/**/*.py"]
    assert config.modules["services"].related == ["ai"]
    assert config.modules["services"].title == "Services"
    assert config.modules["ai"].title == "ai"
    assert config.index.embedding_dim == 384
    assert config.check.max_detail_notes == 10


def test_load_config_when_minimal_file_then_defaults_applied(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, MINIMAL))

    assert config.project.kb_dir == "kb"
    assert config.index.path == "kb/.index/index.sqlite"
    assert config.draft.provider_model == "${MILEPOST_MODEL}"
    assert config.check.fail_on == "stale"
    assert config.structure.languages == ["python"]


def test_load_config_when_module_id_uppercase_then_raises_invalid_config(tmp_path: Path) -> None:
    text = MINIMAL.replace("modules.services", "modules.Services")

    with pytest.raises(InvalidConfig) as error:
        load_config(write_config(tmp_path, text))

    assert "modules.Services" in error.value.field_path


def test_load_config_when_sources_empty_then_raises_invalid_config(tmp_path: Path) -> None:
    text = MINIMAL.replace('["app/services/**/*.py"]', "[]")

    with pytest.raises(InvalidConfig) as error:
        load_config(write_config(tmp_path, text))

    assert error.value.field_path == "modules.services.sources"


def test_load_config_when_glob_absolute_then_raises_invalid_config(tmp_path: Path) -> None:
    text = MINIMAL.replace("app/services/**/*.py", "/etc/**")

    with pytest.raises(InvalidConfig) as error:
        load_config(write_config(tmp_path, text))

    assert error.value.field_path.startswith("modules.services.sources")


def test_load_config_when_glob_contains_parent_ref_then_raises_invalid_config(
    tmp_path: Path,
) -> None:
    text = MINIMAL.replace("app/services/**/*.py", "../outside/**")

    with pytest.raises(InvalidConfig) as error:
        load_config(write_config(tmp_path, text))

    assert error.value.field_path.startswith("modules.services.sources")


def test_load_config_when_related_unknown_module_then_raises_invalid_config(
    tmp_path: Path,
) -> None:
    text = MINIMAL + 'related = ["ghost"]\n'

    with pytest.raises(InvalidConfig) as error:
        load_config(write_config(tmp_path, text))

    assert error.value.field_path == "modules.services.related"
    assert "ghost" in str(error.value)


def test_load_config_when_backend_not_sqlite_then_raises_invalid_config(tmp_path: Path) -> None:
    text = MINIMAL + '\n[index]\nbackend = "postgres"\n'

    with pytest.raises(InvalidConfig) as error:
        load_config(write_config(tmp_path, text))

    assert error.value.field_path == "index.backend"


def test_load_config_when_embedding_dim_zero_then_raises_invalid_config(tmp_path: Path) -> None:
    text = MINIMAL + "\n[index]\nembedding_dim = 0\n"

    with pytest.raises(InvalidConfig) as error:
        load_config(write_config(tmp_path, text))

    assert error.value.field_path == "index.embedding_dim"


def test_load_config_when_structure_root_absolute_then_raises_invalid_config(
    tmp_path: Path,
) -> None:
    text = MINIMAL + '\n[structure]\nroots = ["/abs"]\n'

    with pytest.raises(InvalidConfig) as error:
        load_config(write_config(tmp_path, text))

    assert error.value.field_path.startswith("structure.roots")


def test_load_config_when_roots_omitted_then_defaults_applied(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, MINIMAL))

    assert config.structure.roots == ["src", "app", "backend/app", "packages", "apps"]


def test_load_config_when_max_detail_notes_negative_then_raises_invalid_config(
    tmp_path: Path,
) -> None:
    text = MINIMAL + "\n[check]\nmax_detail_notes = -1\n"

    with pytest.raises(InvalidConfig) as error:
        load_config(write_config(tmp_path, text))

    assert error.value.field_path == "check.max_detail_notes"


def test_load_config_when_missing_file_then_raises_config_not_found(tmp_path: Path) -> None:
    with pytest.raises(ConfigNotFound):
        load_config(tmp_path / "milepost.toml")


def test_resolve_model_when_env_unset_then_raises_with_variable_name(tmp_path: Path) -> None:
    config: Config = load_config(write_config(tmp_path, MINIMAL))

    with pytest.raises(EnvironmentProblem) as error:
        resolve_model(config, {})

    assert "MILEPOST_MODEL" in str(error.value)


def test_resolve_model_when_env_set_then_returns_value(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, MINIMAL))

    assert resolve_model(config, {"MILEPOST_MODEL": "some-model"}) == "some-model"
