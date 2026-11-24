"""The isolated audit stack must agree with its own upgrade-head command."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.config.release_contract import SCHEMA_REVISION
from app.core.config.settings import Settings
from app.infrastructure.runtime_readiness_database import _schema_readiness

ROOT = Path(__file__).resolve().parents[4]


def audit_settings() -> Settings:
    compose = yaml.safe_load((ROOT / "docker-compose.audit.yml").read_text(encoding="utf-8"))
    environment = compose["services"]["backend"]["environment"]
    assert "alembic upgrade head" in compose["services"]["backend"]["command"][-1]
    return Settings(
        **{name.lower(): value for name, value in environment.items()},
        _env_file=None,
    )


def test_packaged_release_revision_is_the_actual_single_migration_head():
    configuration = Config(str(ROOT / "backend/alembic.ini"))
    configuration.set_main_option("script_location", str(ROOT / "backend/alembic"))
    assert ScriptDirectory.from_config(configuration).get_heads() == [SCHEMA_REVISION]


@pytest.mark.parametrize(
    ("versions", "expected"),
    [
        ([SCHEMA_REVISION], ("compatible", True)),
        (["0093_phone_welcome"], ("revision_mismatch", False)),
        ([], ("missing", False)),
        ([SCHEMA_REVISION, "synthetic_other_head"], ("multiple_heads", False)),
    ],
)
async def test_actual_audit_settings_gate_current_and_stale_schema(db_session, versions, expected):
    await db_session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
    for version in versions:
        await db_session.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:version)"),
            {"version": version},
        )
    assert await _schema_readiness(db_session, audit_settings()) == expected
