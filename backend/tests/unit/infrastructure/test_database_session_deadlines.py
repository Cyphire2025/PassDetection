from __future__ import annotations

from app.core.config.settings import DatabaseSettings
from app.infrastructure.database.session import _postgres_server_settings


def test_postgres_server_settings_apply_all_connection_deadlines() -> None:
    database = DatabaseSettings(
        password="test",
        pool_profile="worker",
        worker_statement_timeout_ms=210_000,
        lock_timeout_ms=4_000,
        idle_in_transaction_session_timeout_ms=25_000,
        _env_file=None,
    )

    assert _postgres_server_settings(database) == {
        "statement_timeout": "210000",
        "lock_timeout": "4000",
        "idle_in_transaction_session_timeout": "25000",
    }
