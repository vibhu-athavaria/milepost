import subprocess
from pathlib import Path

from milepost.services.doctor import DoctorReport, run_doctor

MODEL = "openrouter/anthropic/claude-sonnet-4.5"


def keys_present(model: str) -> list[str]:
    return []


def key_missing(model: str) -> list[str]:
    return ["OPENROUTER_API_KEY"]


def status_of(report: DoctorReport, name: str) -> str:
    return next(check.status for check in report.checks if check.name == name)


def test_doctor_when_model_env_unset_then_exit_three_naming_variable(tmp_path: Path) -> None:
    report = run_doctor(tmp_path, {}, keys_present)

    assert report.exit_code == 3
    detail = next(c.detail for c in report.checks if c.name == "MILEPOST_MODEL")
    assert "MILEPOST_MODEL" in detail


def test_doctor_when_provider_key_missing_then_exit_three_naming_variable(tmp_path: Path) -> None:
    report = run_doctor(tmp_path, {"MILEPOST_MODEL": MODEL}, key_missing)

    assert report.exit_code == 3
    detail = next(c.detail for c in report.checks if c.name == "provider-key")
    assert "OPENROUTER_API_KEY" in detail


def test_doctor_when_all_present_then_exit_zero(tmp_path: Path) -> None:
    report = run_doctor(tmp_path, {"MILEPOST_MODEL": MODEL}, keys_present)

    assert report.exit_code == 0
    assert status_of(report, "provider-key") == "ok"


def test_doctor_when_dotenv_not_ignored_then_warns(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".env").write_text("MILEPOST_MODEL=x\n")

    report = run_doctor(tmp_path, {"MILEPOST_MODEL": MODEL}, keys_present)

    assert status_of(report, ".env") == "warn"
    assert report.exit_code == 0


def test_doctor_when_dotenv_ignored_then_no_warning(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".env").write_text("MILEPOST_MODEL=x\n")
    (tmp_path / ".gitignore").write_text(".env\n")

    report = run_doctor(tmp_path, {"MILEPOST_MODEL": MODEL}, keys_present)

    assert all(check.name != ".env" for check in report.checks)


def test_doctor_when_draft_mode_agent_then_no_model_or_key_needed(tmp_path: Path) -> None:
    (tmp_path / "milepost.toml").write_text('[project]\nname = "x"\n\n[draft]\nmode = "agent"\n')

    report = run_doctor(tmp_path, {}, key_missing)

    assert report.exit_code == 0
    assert status_of(report, "draft-mode") == "ok"


def test_doctor_when_config_is_invalid_then_reports_the_config_error(tmp_path: Path) -> None:
    (tmp_path / "milepost.toml").write_text('[project]\nname = "x"\n\n[draft]\nmode = "agnet"\n')

    report = run_doctor(tmp_path, {"MILEPOST_MODEL": MODEL}, keys_present)

    assert status_of(report, "milepost.toml") == "fail"
    assert report.exit_code == 3
