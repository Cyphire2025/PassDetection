#!/usr/bin/env python3
"""Create the initial super administrator after database migrations."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from email_validator import EmailNotValidError, validate_email

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

if TYPE_CHECKING:
    from app.infrastructure.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class SeedAdminInput:
    email: str
    password: str = field(repr=False)
    full_name: str


def _required_environment_value(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def load_seed_input(environ: Mapping[str, str] | None = None) -> SeedAdminInput:
    """Validate credentials before application settings or the database are loaded."""
    resolved_environ = os.environ if environ is None else environ
    raw_email = _required_environment_value(resolved_environ, "ADMIN_EMAIL").strip()
    password = _required_environment_value(resolved_environ, "ADMIN_PASSWORD")

    try:
        email = validate_email(raw_email, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError("ADMIN_EMAIL must be a valid email address") from exc

    # This shared policy module does not load settings or establish DB connections.
    from app.core.security.password import validate_password_strength

    validate_password_strength(password)

    raw_full_name = resolved_environ.get("ADMIN_FULL_NAME")
    full_name = "Super Admin" if raw_full_name is None else raw_full_name.strip()
    if not full_name:
        raise ValueError("ADMIN_FULL_NAME must not be blank")

    return SeedAdminInput(email=email, password=password, full_name=full_name)


async def _create_admin_if_missing(
    seed_input: SeedAdminInput,
    repository: UserRepository,
) -> bool:
    existing = await repository.get_by_email(seed_input.email)
    if existing is not None:
        return False

    from app.core.security.password import hash_password
    from app.domain.entities.entities import User, UserRole

    user = User.create(
        email=seed_input.email,
        hashed_password=hash_password(seed_input.password),
        full_name=seed_input.full_name,
        role=UserRole.SUPER_ADMIN,
    )
    await repository.save(user)
    return True


async def seed(seed_input: SeedAdminInput | None = None) -> None:
    # Fail on invalid credentials before parsing settings or initializing the DB.
    validated_input = seed_input or load_seed_input()

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config.settings import get_settings
    from app.infrastructure.repositories.user_repository import UserRepository

    settings = get_settings()
    engine = create_async_engine(settings.database.async_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            async with session.begin():
                created = await _create_admin_if_missing(
                    validated_input,
                    UserRepository(session),
                )
    finally:
        await engine.dispose()

    if created:
        print(f"[seed] Super admin created: {validated_input.email}")
    else:
        print(f"[seed] Super admin '{validated_input.email}' already exists - skipping.")


def main() -> None:
    try:
        seed_input = load_seed_input()
    except ValueError as exc:
        raise SystemExit(f"[seed] Configuration error: {exc}") from exc
    asyncio.run(seed(seed_input))


if __name__ == "__main__":
    main()
