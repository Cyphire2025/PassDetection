"""Fail closed on any effective privilege that bypasses the runtime boundary."""

import pytest

from app.infrastructure.database.role_policy import require_runtime_role


def test_accepts_restricted_runtime_identity() -> None:
    require_runtime_role((True,) * 7)


@pytest.mark.parametrize("position", range(7))
@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_rejects_privileged_or_unknown_result(position: int, value: object) -> None:
    flags: list[object] = [True] * 7
    flags[position] = value
    with pytest.raises(RuntimeError, match="overprivileged"):
        require_runtime_role(flags)


@pytest.mark.parametrize("flags", [None, (), (True,) * 6, (True,) * 8])
def test_rejects_incomplete_driver_result(flags) -> None:
    with pytest.raises(RuntimeError, match="overprivileged"):
        require_runtime_role(flags)
