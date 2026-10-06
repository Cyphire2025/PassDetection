"""Preserve UUID bytes when PostgreSQL models create disposable SQLite schemas."""

from sqlalchemy import UUID
from sqlalchemy.ext.compiler import compiles


@compiles(UUID, "sqlite")
def compile_sqlite_uuid(_type, _compiler, **_kwargs) -> str:
    # SQLite gives an unknown UUID declaration NUMERIC affinity. Some valid
    # UUID hex strings then become integers, rounded floats, or infinity before
    # SQLAlchemy's UUID result processor sees them. CHAR preserves the existing
    # 32-character binding; production PostgreSQL still compiles native UUID.
    return "CHAR(32)"
