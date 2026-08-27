"""
Alembic Environment Configuration
===================================
Connects Alembic to the application settings and SQLAlchemy models.
Uses synchronous psycopg2 driver (asyncpg cannot be used with Alembic).
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config.settings import get_settings
from app.infrastructure.database import (
    email_ai_models,  # noqa: F401
    email_models,  # noqa: F401
    gc_mobile_models,  # noqa: F401
    menu_models,  # noqa: F401
    my_photos_models,  # noqa: F401
    passport_image_library_model,  # noqa: F401
)
from app.infrastructure.database.models import Base

settings = get_settings()

# ── Alembic Config Object ─────────────────────────────────────────────────────
config = context.config

# Override the sqlalchemy.url from the app settings (no hardcoding)
config.set_main_option("sqlalchemy.url", settings.database.sync_url)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use our models' metadata for autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live database connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
