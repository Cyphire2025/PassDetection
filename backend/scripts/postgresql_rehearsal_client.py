"""PostgreSQL synthetic rehearsal client owner."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

from scripts.postgresql_rehearsal_contract import (
    DESTRUCTIVE_ACKNOWLEDGEMENT,
    PROTECTED_DATABASE_NAMES,
    SAFE_DATABASE_NAME,
)


def validate_database_name(name: str) -> str:
    """Return a safe ephemeral database name or fail closed."""
    # Accepted names are ASCII. PostgreSQL truncates even quoted identifiers at
    # 63 bytes; longer aliases must never bypass the configured-database guard.
    if len(name) > 63 or name in PROTECTED_DATABASE_NAMES or not SAFE_DATABASE_NAME.fullmatch(name):
        raise ValueError(
            "Rehearsal database names must match passdetection_ci_[a-z0-9_]+ "
            "at no more than 63 bytes and may not name a PostgreSQL system database"
        )
    return name


def database_environment(base: Mapping[str, str], database_name: str) -> dict[str, str]:
    """Build an Alembic/client environment without mutating the process environment."""
    environment = dict(base)
    environment["POSTGRES_DB"] = validate_database_name(database_name)
    environment["PGDATABASE"] = database_name
    environment["PGHOST"] = environment["POSTGRES_HOST"]
    environment["PGPORT"] = environment.get("POSTGRES_PORT", "5432")
    environment["PGUSER"] = environment["POSTGRES_USER"]
    environment["PGPASSWORD"] = environment["POSTGRES_PASSWORD"]
    return environment


def require_destructive_acknowledgement(environment: Mapping[str, str]) -> None:
    """Require an explicit acknowledgement before creating/dropping databases."""
    if environment.get(DESTRUCTIVE_ACKNOWLEDGEMENT) != "1":
        raise RuntimeError(
            f"Set {DESTRUCTIVE_ACKNOWLEDGEMENT}=1 only for isolated rehearsal databases"
        )


def _run(
    arguments: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(arguments), flush=True)
    return subprocess.run(
        list(arguments),
        cwd=cwd,
        env=dict(environment),
        check=True,
        text=True,
        capture_output=capture_output,
        shell=False,
    )


def _connect(environment: Mapping[str, str], database_name: str) -> Connection:
    return psycopg2.connect(
        host=environment["POSTGRES_HOST"],
        port=int(environment.get("POSTGRES_PORT", "5432")),
        user=environment["POSTGRES_USER"],
        password=environment["POSTGRES_PASSWORD"],
        dbname=database_name,
        connect_timeout=10,
        application_name="passdetection-migration-rehearsal",
    )


def _drop_database(environment: Mapping[str, str], database_name: str) -> None:
    database_name = validate_database_name(database_name)
    connection = _connect(environment, "postgres")
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )
    finally:
        connection.close()


def _create_database(environment: Mapping[str, str], database_name: str) -> None:
    database_name = validate_database_name(database_name)
    connection = _connect(environment, "postgres")
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    finally:
        connection.close()


def _replace_database(environment: Mapping[str, str], database_name: str) -> None:
    _drop_database(environment, database_name)
    _create_database(environment, database_name)


def _alembic(
    backend_root: Path,
    environment: Mapping[str, str],
    *arguments: str,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=backend_root,
        environment=environment,
        capture_output=capture_output,
    )


def _client_major(version_output: str) -> int:
    match = re.search(r"\b(\d+)(?:\.\d+)?\b", version_output)
    if match is None:
        raise ValueError(f"Could not parse PostgreSQL client version from {version_output!r}")
    return int(match.group(1))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timed_stage(timings: dict[str, float], name: str, operation: Any) -> Any:
    started = time.monotonic()
    try:
        return operation()
    finally:
        timings[name] = round(time.monotonic() - started, 3)


# Preserve canonical public import/pickle identities through the CLI facade.
for _export in (
    validate_database_name,
    database_environment,
    require_destructive_acknowledgement,
    _run,
    _connect,
    _drop_database,
    _create_database,
    _replace_database,
    _alembic,
    _client_major,
    _sha256,
    _timed_stage,
):
    _export.__module__ = "scripts.rehearse_postgresql_upgrade"
del _export
