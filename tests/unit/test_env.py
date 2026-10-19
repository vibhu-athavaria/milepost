import pytest

from milepost.env import is_disabled


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_is_disabled_when_value_is_truthy_then_true(value: str) -> None:
    assert is_disabled({"MILEPOST_DISABLED": value}) is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_is_disabled_when_value_is_not_truthy_then_false(value: str) -> None:
    assert is_disabled({"MILEPOST_DISABLED": value}) is False


def test_is_disabled_when_unset_then_false() -> None:
    assert is_disabled({}) is False
