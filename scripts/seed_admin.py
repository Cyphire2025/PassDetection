#!/usr/bin/env python3
"""
Seed Script — Create Initial Super Admin User
=============================================
Run once after running migrations to bootstrap the platform.

Usage:
    python scripts/seed_admin.py

Environment variables required:
    ADMIN_EMAIL     — email for the super admin account
    ADMIN_PASSWORD  — password (min 8 chars)
    ADMIN_FULL_NAME — display name
"""

from __future__ import annotations

import asyncio
import os
import sys

# Allow running from any directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config.settings import get_settings
from app.core.security.password import hash_password
from app.domain.entities.entities import User, UserRole
from app.infrastructure.repositories.user_repository import UserRepository

settings = get_settings()


async def seed() -> None:
    email     = os.environ.get("ADMIN_EMAIL",     "admin@passdetection.com")
    password  = os.environ.get("ADMIN_PASSWORD",  "Admin@1234!")
    full_name = os.environ.get("ADMIN_FULL_NAME", "Super Admin")

    engine = create_async_engine(settings.database.async_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        async with session.begin():
            repo = UserRepository(session)

            existing = await repo.get_by_email(email)
            if existing:
                print(f"[seed] Super admin '{email}' already exists — skipping.")
                return

            user = User.create(
                email=email,
                hashed_password=hash_password(password),
                full_name=full_name,
                role=UserRole.SUPER_ADMIN,
            )
            await repo.save(user)
            print(f"[seed] Super admin created: {email}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
