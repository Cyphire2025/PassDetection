from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _load_migration() -> Any:
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0068_document_chunk_limits.py"
    )
    spec = importlib.util.spec_from_file_location(
        "document_upload_chunk_limits_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _recording_operations(calls: list[tuple[str, ...]]) -> SimpleNamespace:
    return SimpleNamespace(
        drop_constraint=lambda name, table, *, type_: calls.append(("drop", name, table, type_)),
        create_check_constraint=lambda name, table, condition: calls.append(
            ("create", name, table, condition)
        ),
    )


def test_upgrade_replaces_only_chunk_capacity_checks_with_fifty() -> None:
    migration = _load_migration()
    calls: list[tuple[str, ...]] = []
    migration.op = _recording_operations(calls)

    migration.upgrade()

    assert calls == [
        (
            "drop",
            "ck_document_upload_chunks_manifest_capacity",
            "document_upload_chunks",
            "check",
        ),
        (
            "drop",
            "ck_document_upload_chunks_file_count",
            "document_upload_chunks",
            "check",
        ),
        (
            "create",
            "ck_document_upload_chunks_manifest_capacity",
            "document_upload_chunks",
            "expected_file_count >= expected_chunk_count "
            "AND expected_file_count <= expected_chunk_count * 50",
        ),
        (
            "create",
            "ck_document_upload_chunks_file_count",
            "document_upload_chunks",
            "file_count BETWEEN 1 AND 50",
        ),
    ]


def test_downgrade_restores_the_original_twenty_five_file_checks() -> None:
    migration = _load_migration()
    calls: list[tuple[str, ...]] = []
    migration.op = _recording_operations(calls)

    migration.downgrade()

    assert calls[-2:] == [
        (
            "create",
            "ck_document_upload_chunks_manifest_capacity",
            "document_upload_chunks",
            "expected_file_count >= expected_chunk_count "
            "AND expected_file_count <= expected_chunk_count * 25",
        ),
        (
            "create",
            "ck_document_upload_chunks_file_count",
            "document_upload_chunks",
            "file_count BETWEEN 1 AND 25",
        ),
    ]


def test_original_migration_remains_immutable_at_twenty_five() -> None:
    original_source = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0067_document_upload_chunks.py"
    ).read_text(encoding="utf-8")

    assert "expected_chunk_count * 25" in original_source
    assert "file_count BETWEEN 1 AND 25" in original_source
