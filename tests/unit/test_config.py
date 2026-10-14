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
    assert config.check.stale == "fail"


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


def test_load_config_when_stale_mode_invalid_then_raises_invalid_config(tmp_path: Path) -> None:
    text = MINIMAL + '\n[check]\nstale = "sometimes"\n'

    with pytest.raises(InvalidConfig) as error:
        load_config(write_config(tmp_path, text))

    assert error.value.field_path == "check.stale"


def test_load_config_when_no_check_table_then_stale_notes_only_warn(tmp_path: Path) -> None:
    assert load_config(write_config(tmp_path, MINIMAL)).check.stale == "warn"


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


def test_config_when_module_verify_list_then_parsed(tmp_path: Path) -> None:
    text = MINIMAL + 'verify = ["pytest app/tests/services", "ruff check app/services"]\n'

    config = load_config(write_config(tmp_path, text))

    assert config.modules["services"].verify == [
        "pytest app/tests/services",
        "ruff check app/services",
    ]


def test_config_when_no_verify_then_empty_list(tmp_path: Path) -> None:
    assert load_config(write_config(tmp_path, MINIMAL)).modules["services"].verify == []


def test_config_when_draft_mode_invalid_then_exit_two(tmp_path: Path) -> None:
    with pytest.raises(InvalidConfig) as error:
        load_config(write_config(tmp_path, MINIMAL + '\n[draft]\nmode = "robot"\n'))

    assert error.value.exit_code == 2 and error.value.field_path == "draft.mode"


def test_config_when_draft_mode_is_set_then_accepted_and_default_is_agent(tmp_path: Path) -> None:
    model = load_config(write_config(tmp_path, MINIMAL + '\n[draft]\nmode = "model"\n'))
    default = load_config(write_config(tmp_path, MINIMAL))

    assert model.draft.mode == "model" and default.draft.mode == "agent"


@pytest.mark.parametrize("spelling", ["kb/", "./kb", "kb", "kb//"])
def test_load_config_when_kb_dir_has_odd_spelling_then_normalised(
    tmp_path: Path, spelling: str
) -> None:
    text = f'[project]\nname = "x"\nkb_dir = "{spelling}"\n'

    assert load_config(write_config(tmp_path, text)).project.kb_dir == "kb"


@pytest.mark.parametrize("bad", ["/abs", "../up", "."])
def test_load_config_when_kb_dir_leaves_the_repo_then_invalid(tmp_path: Path, bad: str) -> None:
    with pytest.raises(InvalidConfig) as error:
        load_config(write_config(tmp_path, f'[project]\nname = "x"\nkb_dir = "{bad}"\n'))

    assert error.value.field_path == "project.kb_dir"
