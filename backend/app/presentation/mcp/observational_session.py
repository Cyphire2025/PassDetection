"""Block business DML and commits even if a reviewed website reader regresses.

The outer MCP transaction retains its authority locks and commits its audit.
Only audit-ledger maintenance is permitted inside a dashboard observation.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause


class NonObservationalDashboardRead(RuntimeError):
    pass


@asynccontextmanager
async def observational_session(session: AsyncSession) -> AsyncIterator[None]:
    await session.flush()  # Complete the outer token last-used bookkeeping first.
    connection = (await session.connection()).sync_connection
    audit_tables = {"audit_logs", "audit_chain_heads"}

    def before_execute(_connection: Any, clause: Any, _multiparams: Any, _params: Any, _options: Any) -> None:
        if getattr(clause, "is_dml", False):
            if getattr(getattr(clause, "table", None), "name", None) not in audit_tables:
                raise NonObservationalDashboardRead("Business writes are forbidden during an MCP dashboard read")
        elif isinstance(clause, TextClause):
            if not clause.text.lstrip().upper().startswith("SELECT "):
                raise NonObservationalDashboardRead("Unreviewed SQL is forbidden during an MCP dashboard read")
        elif not getattr(clause, "is_select", False):
            raise NonObservationalDashboardRead("Only observational queries are permitted")

    def before_flush(sync_session: Any, _context: Any, _instances: Any) -> None:
        for row in (*sync_session.new, *sync_session.dirty, *sync_session.deleted):
            if row.__table__.name not in audit_tables:
                raise NonObservationalDashboardRead("Business writes are forbidden during an MCP dashboard read")

    def before_commit(_session: Any) -> None:
        raise NonObservationalDashboardRead("A dashboard read cannot commit the MCP transaction")

    event.listen(connection, "before_execute", before_execute)
    event.listen(session.sync_session, "before_flush", before_flush)
    event.listen(session.sync_session, "before_commit", before_commit)
    try:
        yield
        # A reader may dirty an ORM object without flushing. The outer MCP
        # commit must never persist such a deferred business write after these
        # hooks are removed. Invocation rolls the transaction back on failure.
        before_flush(session.sync_session, None, None)
    finally:
        event.remove(connection, "before_execute", before_execute)
        event.remove(session.sync_session, "before_flush", before_flush)
        event.remove(session.sync_session, "before_commit", before_commit)
