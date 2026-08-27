from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import sqlalchemy as sa

from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoDeliveryAuthorizationModel,
    MyPhotoMediaAssetModel,
)

_TABLES = (
    "my_photo_galleries",
    "my_photo_gallery_manifests",
    "my_photo_gallery_manifest_batches",
    "my_photo_media_assets",
    "my_photo_asset_variants",
    "my_photo_face_occurrences",
    "my_photo_enrollments",
    "my_photo_liveness_sessions",
    "my_photo_search_runs",
    "my_photo_matches",
    "my_photo_jobs",
    "my_photo_delivery_authorizations",
)


def test_my_photos_manifest_migration_supports_cancelled_revision_retry_and_long_versions() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    active_revision = next(
        call
        for call in operation_proxy.create_index.call_args_list
        if call.args[0] == "uq_my_photo_manifest_active_revision"
    )
    assert active_revision.args[2] == ["gallery_id", "target_revision"]
    assert active_revision.kwargs["unique"] is True
    assert str(active_revision.kwargs["postgresql_where"]) == "status <> 'cancelled'"

    assets = _table_call(operation_proxy, "my_photo_media_assets")
    asset_columns = {item.name: item for item in assets.args[1:] if isinstance(item, sa.Column)}
    assert asset_columns["archive_reference"].type.length == 4096
    assert asset_columns["storage_reference"].type.length == 4096


def _load_migration():  # type: ignore[no-untyped-def]
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0086_my_photos_foundation.py"
    )
    spec = importlib.util.spec_from_file_location("my_photos_foundation_migration", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"alembic": SimpleNamespace(op=MagicMock())}):
        spec.loader.exec_module(module)
    return module


def _table_call(operation_proxy: MagicMock, table_name: str):  # type: ignore[no-untyped-def]
    return next(
        call for call in operation_proxy.create_table.call_args_list if call.args[0] == table_name
    )


def _foreign_keys(table_call) -> dict[str | None, sa.ForeignKeyConstraint]:  # type: ignore[no-untyped-def]
    return {
        item.name: item for item in table_call.args[1:] if isinstance(item, sa.ForeignKeyConstraint)
    }


def _check_constraints(table_call) -> dict[str | None, sa.CheckConstraint]:  # type: ignore[no-untyped-def]
    return {item.name: item for item in table_call.args[1:] if isinstance(item, sa.CheckConstraint)}


def test_my_photos_migration_has_one_head_parent_and_reversible_table_order() -> None:
    migration = _load_migration()
    assert migration.revision == "0086_my_photos_foundation"
    assert migration.down_revision == "0085_platform_retention_controls"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()
        migration.downgrade()

    assert tuple(call.args[0] for call in operation_proxy.create_table.call_args_list) == _TABLES
    assert tuple(call.args[0] for call in operation_proxy.drop_table.call_args_list) == tuple(
        reversed(_TABLES)
    )


def test_my_photos_migration_enforces_scoped_match_integrity_and_active_uniqueness() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    match_call = _table_call(operation_proxy, "my_photo_matches")
    foreign_keys = _foreign_keys(match_call)
    assert tuple(foreign_keys["fk_my_photo_match_search"].column_keys) == (
        "search_run_id",
        "passenger_identity_id",
        "agency_id",
        "group_id",
    )
    assert tuple(foreign_keys["fk_my_photo_match_asset"].column_keys) == (
        "media_asset_id",
        "agency_id",
        "group_id",
    )
    assert tuple(foreign_keys["fk_my_photo_match_face"].column_keys) == (
        "face_occurrence_id",
        "media_asset_id",
        "agency_id",
        "group_id",
    )

    active_index = next(
        call
        for call in operation_proxy.create_index.call_args_list
        if call.args[0] == "uq_my_photo_match_active_asset"
    )
    assert active_index.args[2] == ["passenger_identity_id", "media_asset_id"]
    assert active_index.kwargs["unique"] is True
    assert str(active_index.kwargs["postgresql_where"]) == "active = true"


def test_my_photos_migration_scopes_assets_and_faces_to_gallery_tenant_and_group() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    asset_fks = _foreign_keys(_table_call(operation_proxy, "my_photo_media_assets"))
    assert tuple(asset_fks["fk_my_photo_asset_gallery"].column_keys) == (
        "gallery_id",
        "agency_id",
        "group_id",
    )
    face_fks = _foreign_keys(_table_call(operation_proxy, "my_photo_face_occurrences"))
    assert tuple(face_fks["fk_my_photo_face_asset"].column_keys) == (
        "media_asset_id",
        "agency_id",
        "group_id",
    )


def test_my_photos_migration_caps_every_mobile_deliverable_item_at_200_mib() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    asset_checks = _check_constraints(_table_call(operation_proxy, "my_photo_media_assets"))
    variant_checks = _check_constraints(_table_call(operation_proxy, "my_photo_asset_variants"))
    delivery_checks = _check_constraints(
        _table_call(operation_proxy, "my_photo_delivery_authorizations")
    )

    assert str(asset_checks["ck_my_photo_asset_size"].sqltext) == (
        "byte_size BETWEEN 1 AND 209715200"
    )
    assert "byte_size BETWEEN 1 AND 209715200" in str(
        variant_checks["ck_my_photo_variant_dimensions"].sqltext
    )
    assert str(delivery_checks["ck_my_photo_delivery_size"].sqltext) == (
        "expected_size_bytes IS NULL OR expected_size_bytes BETWEEN 1 AND 209715200"
    )


def test_my_photos_orm_uses_the_same_200_mib_constraints_as_the_migration() -> None:
    def checks(model: type[object]) -> dict[str | None, sa.CheckConstraint]:
        return {
            item.name: item
            for item in model.__table__.constraints  # type: ignore[attr-defined]
            if isinstance(item, sa.CheckConstraint)
        }

    asset_checks = checks(MyPhotoMediaAssetModel)
    variant_checks = checks(MyPhotoAssetVariantModel)
    delivery_checks = checks(MyPhotoDeliveryAuthorizationModel)

    assert str(asset_checks["ck_my_photo_asset_size"].sqltext) == (
        "byte_size BETWEEN 1 AND 209715200"
    )
    assert "byte_size BETWEEN 1 AND 209715200" in str(
        variant_checks["ck_my_photo_variant_dimensions"].sqltext
    )
    assert str(delivery_checks["ck_my_photo_delivery_size"].sqltext) == (
        "expected_size_bytes IS NULL OR expected_size_bytes BETWEEN 1 AND 209715200"
    )
