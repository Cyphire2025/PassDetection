from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import sqlalchemy as sa

from app.infrastructure.database.gc_mobile_models import ClientManagerProfileModel


def _load_migration():  # type: ignore[no-untyped-def]
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0077_gc_app_admin_list_index.py"
    )
    spec = importlib.util.spec_from_file_location("gc_app_admin_list_index", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gc_app_admin_list_index_is_online_tenant_scoped_and_partial() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    migration.op = operation_proxy

    migration.upgrade()

    operation_proxy.get_context.return_value.autocommit_block.assert_called_once()
    call = operation_proxy.create_index.call_args
    assert call.args == (
        "ix_client_manager_admin_list",
        "client_manager_profiles",
        ["agency_id", "created_at", "id"],
    )
    assert call.kwargs["unique"] is False
    assert isinstance(call.kwargs["postgresql_where"], sa.sql.elements.TextClause)
    assert str(call.kwargs["postgresql_where"]) == "deleted_at IS NULL"
    assert call.kwargs["postgresql_concurrently"] is True
    assert call.kwargs["if_not_exists"] is True


def test_gc_app_admin_list_index_downgrade_is_online() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    migration.op = operation_proxy

    migration.downgrade()

    operation_proxy.drop_index.assert_called_once_with(
        "ix_client_manager_admin_list",
        table_name="client_manager_profiles",
        postgresql_concurrently=True,
        if_exists=True,
    )


def test_gc_app_admin_list_index_is_declared_in_orm_metadata() -> None:
    index = next(
        item
        for item in ClientManagerProfileModel.__table__.indexes
        if item.name == "ix_client_manager_admin_list"
    )

    assert [column.name for column in index.columns] == ["agency_id", "created_at", "id"]
    assert str(index.dialect_options["postgresql"]["where"]) == "deleted_at IS NULL"
