"""Independent local audit storage and a non-swallowable global-factory guard."""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.database.models import AuditChainHeadModel, AuditLogModel, Base
from app.presentation.mcp import management_audit


@pytest.fixture(autouse=True)
def forbid_global_management_audit_database(monkeypatch):
    def forbidden_factory():
        # pytest.fail raises outside Exception, so the application's availability
        # fallback cannot conceal an unbound test or attempt a network connection.
        pytest.fail("Bind an isolated mcp_management_audit_session_factory in this test app")

    monkeypatch.setattr(management_audit, "AsyncSessionFactory", forbidden_factory)


@pytest.fixture
async def management_audit_session_factory(tmp_path_factory):
    """Only audit tables; never share the business engine, connection or session.

    Audit actor/scope UUID columns intentionally have no foreign keys in the
    real models. This fixture proves local transaction isolation, not PostgreSQL
    locking or production authorization/foreign-key behavior.
    """
    # A consumer can use its whole tmp_path as a sealed diagnostic root. Keep
    # this supporting database in a separate fixture-owned directory.
    audit_directory = tmp_path_factory.mktemp("management-audit")
    engine = create_async_engine(f"sqlite+aiosqlite:///{audit_directory / 'management-audit.sqlite'}")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _record):
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    async with engine.begin() as connection:
        assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
        await connection.run_sync(
            lambda sync: Base.metadata.create_all(
                sync, tables=[AuditChainHeadModel.__table__, AuditLogModel.__table__]
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
