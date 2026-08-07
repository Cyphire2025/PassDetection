from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def _load_seed_script():  # type: ignore[no-untyped-def]
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "seed_admin.py"
    module_name = "seed_admin_script_under_test"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_seed_input_requires_email_and_password() -> None:
    seed_admin = _load_seed_script()

    with pytest.raises(ValueError, match="ADMIN_EMAIL is required"):
        seed_admin.load_seed_input({"ADMIN_PASSWORD": "StrongPassword123"})

    with pytest.raises(ValueError, match="ADMIN_PASSWORD is required"):
        seed_admin.load_seed_input({"ADMIN_EMAIL": "owner@example.com"})


def test_seed_input_validates_and_normalizes_credentials() -> None:
    seed_admin = _load_seed_script()

    with pytest.raises(ValueError, match="ADMIN_EMAIL must be a valid email address"):
        seed_admin.load_seed_input(
            {"ADMIN_EMAIL": "not-an-email", "ADMIN_PASSWORD": "StrongPassword123"}
        )

    with pytest.raises(ValueError, match="Password must be at least"):
        seed_admin.load_seed_input(
            {"ADMIN_EMAIL": "owner@example.com", "ADMIN_PASSWORD": "Short1A"}
        )

    seed_input = seed_admin.load_seed_input(
        {
            "ADMIN_EMAIL": " Owner@Example.COM ",
            "ADMIN_PASSWORD": "StrongPassword123",
        }
    )
    assert seed_input.email == "owner@example.com"
    assert seed_input.full_name == "Super Admin"
    assert "StrongPassword123" not in repr(seed_input)


@pytest.mark.asyncio
async def test_seed_validates_credentials_before_loading_settings_or_database() -> None:
    seed_admin = _load_seed_script()

    with patch.dict(os.environ, {"ADMIN_PASSWORD": "StrongPassword123"}, clear=True):
        with pytest.raises(ValueError, match="ADMIN_EMAIL is required"):
            await seed_admin.seed()


@pytest.mark.asyncio
async def test_existing_admin_is_left_unchanged() -> None:
    seed_admin = _load_seed_script()
    seed_input = seed_admin.load_seed_input(
        {
            "ADMIN_EMAIL": "owner@example.com",
            "ADMIN_PASSWORD": "StrongPassword123",
        }
    )
    repository = AsyncMock()
    repository.get_by_email.return_value = object()

    created = await seed_admin._create_admin_if_missing(seed_input, repository)

    assert created is False
    repository.get_by_email.assert_awaited_once_with("owner@example.com")
    repository.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_admin_is_created_as_super_admin() -> None:
    seed_admin = _load_seed_script()
    seed_input = seed_admin.load_seed_input(
        {
            "ADMIN_EMAIL": "OWNER@example.com",
            "ADMIN_PASSWORD": "StrongPassword123",
            "ADMIN_FULL_NAME": "Platform Owner",
        }
    )
    repository = AsyncMock()
    repository.get_by_email.return_value = None

    with patch("app.core.security.password.hash_password", return_value="hashed-password"):
        created = await seed_admin._create_admin_if_missing(seed_input, repository)

    assert created is True
    repository.save.assert_awaited_once()
    user = repository.save.await_args.args[0]
    assert user.email == "owner@example.com"
    assert user.hashed_password == "hashed-password"
    assert user.full_name == "Platform Owner"
    assert user.role.value == "super_admin"
