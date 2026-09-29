"""Retained isolated DB/archive proof for the exact direct-release database helper."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]
ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"


def test_direct_backup_decode_exact_upgrade_and_retry_retain_source_data():
    host, original = os.environ.get("POSTGRES_HOST", "localhost"), os.environ["POSTGRES_DB"]
    if host not in {"127.0.0.1", "localhost", "db", "postgres"} or not (
        original == "test_db" or original.startswith("passdetection_ci_")
    ):
        pytest.fail("Direct database qualification requires an isolated local/CI cluster")
    sys.path.insert(0, str(ROOT / "scripts"))
    from release_mcp_contract import CHAIN, SOURCE
    from release_mcp_database import DUMP_COMMAND, MCPDatabaseRelease, ReleaseBindings

    suffix = uuid.uuid4().hex[:12]
    database, owner = "passdetection_ci_mcp_direct_" + suffix, "mcp_direct_" + suffix
    password = "synthetic-direct-" + suffix
    environment = {
        **os.environ,
        "POSTGRES_DB": database,
        "POSTGRES_USER": owner,
        "POSTGRES_PASSWORD": password,
        "PGPASSWORD": password,
        "APP_SECRET_KEY": "isolated-direct-release-check-not-production",
        "PYTHONUTF8": "1",
    }
    admin = psycopg2.connect(
        host=host,
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=original,
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )
    admin.autocommit = True
    with admin.cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(sql.Identifier(owner)), (password,)
        )
        cursor.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database), sql.Identifier(owner)
            )
        )
    admin.close()
    connection = psycopg2.connect(
        host=host,
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=database,
        user=owner,
        password=password,
    )
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(owner)))

    def command(arguments, *, timeout=120, env=None):
        result = subprocess.run(
            [sys.executable, *arguments],
            cwd=BACKEND,
            env=env or environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        assert result.returncode == 0, result.stdout.decode(errors="replace")[-3000:]
        return result.stdout.decode(errors="replace")

    command(["-m", "alembic", "upgrade", SOURCE])
    identifier = uuid.uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO agencies(id,name,email,created_at,updated_at) VALUES (%s,'Retained direct helper fixture','synthetic@example.test',now(),now())",
            (str(identifier),),
        )
    directory = ROOT / "outputs" / ("mcp-direct-database-" + suffix)
    directory.mkdir(mode=0o700)

    def executable(name):
        local = ROOT / "outputs/mcp-postgresql-16.15/pgsql/bin" / (name + ".exe")
        value = str(local) if os.name == "nt" and local.is_file() else shutil.which(name)
        assert value, f"Required qualification executable missing: {name}"
        return value

    def database_command(arguments, *, timeout, stdin_file=None, stdout_file=None):
        if arguments == ("sh", "-c", DUMP_COMMAND):
            args = [
                executable("pg_dump"),
                "-h",
                host,
                "-p",
                environment.get("POSTGRES_PORT", "5432"),
                "-U",
                owner,
                "-d",
                database,
                "--format=custom",
                "--lock-wait-timeout=5000",
            ]
        else:
            args = [
                executable("pg_restore"),
                *(
                    "--file=" + os.devnull if value == "--file=/dev/null" else value
                    for value in arguments[1:]
                ),
            ]
        result = subprocess.run(
            args,
            env={**environment, "PGOPTIONS": "-c lock_timeout=5000 -c statement_timeout=120000"},
            stdin=stdin_file,
            stdout=stdout_file or subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        assert result.returncode == 0, "Synthetic PostgreSQL archive command failed"
        return "" if stdout_file else result.stdout.decode()

    fence_checks = 0

    def verify_fence():
        nonlocal fence_checks
        fence_checks += 1
        # This database has no application clients, workers, schedulers or public
        # traffic. The real executor must verify all of those live bindings.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()"
            )
            assert cursor.fetchone()[0] == 0

    def schema():
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM public.alembic_version")
            return cursor.fetchone()[0]

    release = MCPDatabaseRelease(
        ROOT,
        directory.resolve(),
        ReleaseBindings("a" * 40, "sha256:" + "b" * 64, "c" * 64, "d" * 64),
        database_command=database_command,
        verify_fence=verify_fence,
        read_schema=schema,
    )
    try:
        backup = release.backup()
        request = release.migration_request(backup)
        broken = json.loads(request["arguments"][-1])
        broken["migrations"][0]["sha256"] = "0" * 64
        rejected = subprocess.run(
            [
                sys.executable,
                "scripts/apply_mcp_additive_upgrade.py",
                "--contract-json",
                json.dumps(broken),
            ],
            cwd=BACKEND,
            env={**environment, **request["environment"]},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        assert rejected.returncode == 2 and schema() == SOURCE
        assert b"synthetic-direct-" not in rejected.stdout + rejected.stderr
        # A retained source table lock must fail within the fixed five-second
        # lock budget, roll back the whole additive chain, and permit retry.
        with connection.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute("LOCK TABLE users IN ACCESS EXCLUSIVE MODE")
        try:
            blocked = subprocess.run(
                [sys.executable, *list(request["arguments"])[1:]],
                cwd=BACKEND,
                env={**environment, **request["environment"]},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            assert blocked.returncode == 2
            assert b"additive_upgrade_failed" in blocked.stdout
            assert b"synthetic-direct-" not in blocked.stdout + blocked.stderr
        finally:
            with connection.cursor() as cursor:
                cursor.execute("ROLLBACK")
        assert schema() == SOURCE
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.mcp_control')")
            assert cursor.fetchone() == (None,)
        output = command(
            list(request["arguments"])[1:], env={**environment, **request["environment"]}
        )
        assert '"status": "upgraded"' in output and schema() == CHAIN[-1]
        release.verify_target(backup)
        retry = release.migration_request(backup)
        assert retry["already_at_target"]
        output = command(list(retry["arguments"])[1:], env={**environment, **retry["environment"]})
        assert '"status": "already_at_target"' in output
        with connection.cursor() as cursor:
            cursor.execute("SELECT name FROM agencies WHERE id=%s", (str(identifier),))
            assert cursor.fetchone() == ("Retained direct helper fixture",)
            cursor.execute("SELECT enabled FROM mcp_control WHERE id=1")
            assert cursor.fetchone() == (False,)
        assert fence_checks >= 6 and len(list(directory.iterdir())) == 2
        assert release.verify_backup(backup).is_file()
    finally:
        connection.close()
        # Retain this uniquely owned database/role/archive/receipt for review.
