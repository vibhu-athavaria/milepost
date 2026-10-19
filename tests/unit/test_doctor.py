import importlib.util
from pathlib import Path

import pytest

from milepost.services.doctor import DoctorReport, run_doctor


def status_of(report: DoctorReport, name: str) -> str:
    return next(check.status for check in report.checks if check.name == name)


def test_doctor_when_environment_is_fine_then_exit_zero(tmp_path: Path) -> None:
    report = run_doctor(tmp_path)

    assert report.exit_code == 0
    assert status_of(report, "git") == "ok" and status_of(report, "sqlite-fts5") == "ok"


def test_doctor_when_config_is_invalid_then_reports_the_config_error(tmp_path: Path) -> None:
    (tmp_path / "milepost.toml").write_text('[project]\nname = "x"\n\n[structure]\nbogus = 1\n')

    report = run_doctor(tmp_path)

    assert status_of(report, "milepost.toml") == "fail"
    assert report.exit_code == 3


def test_doctor_when_config_still_has_the_removed_separate_model_setting_then_warns_to_delete_it(
    tmp_path: Path,
) -> None:
    (tmp_path / "milepost.toml").write_text('[project]\nname = "x"\n\n[draft]\nmode = "model"\n')

    report = run_doctor(tmp_path)

    detail = next(c.detail for c in report.checks if c.name == "milepost.toml")
    assert "mode is ignored" in detail and "delete the line" in detail
    assert status_of(report, "milepost.toml") == "warn" and report.exit_code == 0


def test_doctor_when_config_has_the_old_agent_setting_then_it_is_fine(tmp_path: Path) -> None:
    (tmp_path / "milepost.toml").write_text(
        '[project]\nname = "x"\n\n[draft]\nmode = "agent"\nprovider_model = "${MILEPOST_MODEL}"\n'
    )

    assert run_doctor(tmp_path).exit_code == 0


def test_doctor_when_search_extra_missing_then_warns_keyword_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "fastembed" else real(name, *a),
    )

    report = run_doctor(tmp_path)

    assert status_of(report, "search") == "warn" and report.exit_code == 0
