"""Credential encoding must survive both runtime parsing and Alembic config."""

import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.core.config.settings import DatabaseSettings


@pytest.mark.parametrize("password", ["pa@ss/word", "a:b%23#?&=", "päss 密碼", "ordinary"])
@pytest.mark.parametrize("host", ["database.internal", "::1"])
def test_database_credentials_round_trip(password: str, host: str) -> None:
    settings = DatabaseSettings(
        _env_file=None, user="app@tenant", password=password, host=host, db="app_db"
    )
    for rendered in (settings.async_url, settings.sync_url):
        parsed = make_url(rendered)
        assert (parsed.username, parsed.password, parsed.host, parsed.database) == (
            "app@tenant", password, host, "app_db"
        )
        assert parsed.port == 5432


def test_alembic_preserves_percent_encoded_password() -> None:
    settings = DatabaseSettings(_env_file=None, password="@/%:密碼#")
    config = Config()
    config.set_main_option("sqlalchemy.url", settings.sync_url.replace("%", "%%"))
    assert make_url(config.get_main_option("sqlalchemy.url")).password == settings.password
