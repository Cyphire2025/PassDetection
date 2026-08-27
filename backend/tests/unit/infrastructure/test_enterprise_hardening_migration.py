from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import sqlalchemy as sa

from app.infrastructure.database.models import (
    AttendanceDiscardTombstoneModel,
    AttendanceRuntimeRegistrationModel,
    AttendanceScanBatchModel,
    AttendanceScanBatchResultModel,
    AttendanceSessionRuntimeParticipantModel,
    AuditChainHeadModel,
    IdentityNotificationOutboxModel,
    UntrustedUploadScanModel,
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3] / "alembic" / "versions" / "0087_enterprise_hardening.py"
)
ROOMING_MIGRATION_PATH = (
    Path(__file__).resolve().parents[3] / "alembic" / "versions" / "0016_rooming_lists.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "enterprise_hardening_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade() -> tuple[ModuleType, MagicMock]:
    migration = _load_migration()
    operation = MagicMock()
    migration.op = operation
    migration.upgrade()
    return migration, operation


def _created_tables(operation: MagicMock) -> dict[str, tuple[object, ...]]:
    return {call.args[0]: call.args[1:] for call in operation.create_table.call_args_list}


def _column_names(elements: tuple[object, ...]) -> set[str]:
    return {element.name for element in elements if isinstance(element, sa.Column)}


def _constraint_names(elements: tuple[object, ...]) -> set[str | None]:
    return {element.name for element in elements if isinstance(element, sa.Constraint)}


def test_revision_is_an_intentional_sibling_of_reserved_my_photos_revision() -> None:
    migration = _load_migration()

    assert migration.revision == "0087_enterprise_hardening"
    assert migration.down_revision == "0085_platform_retention_controls"
    assert migration.branch_labels is None
    assert migration.depends_on is None
    assert len(migration.revision) <= 32


def test_migration_preserves_rooming_updated_at_owned_by_revision_0016() -> None:
    _, upgrade_operation = _run_upgrade()
    migration = _load_migration()
    downgrade_operation = MagicMock()
    migration.op = downgrade_operation
    migration.downgrade()

    assert all(
        call.args[:2] != ("rooming_hotels", "updated_at")
        for call in upgrade_operation.add_column.call_args_list
    )
    assert all(
        call.args[:2] != ("rooming_hotels", "updated_at")
        for call in upgrade_operation.alter_column.call_args_list
    )
    assert all(
        call.args[:2] != ("rooming_hotels", "updated_at")
        for call in downgrade_operation.drop_column.call_args_list
    )

    spec = importlib.util.spec_from_file_location("rooming_lists_migration", ROOMING_MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    rooming_migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rooming_migration)
    rooming_operation = MagicMock()
    rooming_migration.op = rooming_operation
    rooming_migration.upgrade()
    rooming_table = next(
        call.args[1:]
        for call in rooming_operation.create_table.call_args_list
        if call.args[0] == "rooming_hotels"
    )
    updated_at = next(
        element
        for element in rooming_table
        if isinstance(element, sa.Column) and element.name == "updated_at"
    )
    assert updated_at.nullable is False


def test_new_table_columns_match_the_current_orm_exactly() -> None:
    _, operation = _run_upgrade()
    created = _created_tables(operation)
    expected_models = {
        "attendance_runtime_registrations": AttendanceRuntimeRegistrationModel,
        "attendance_session_runtime_participants": (AttendanceSessionRuntimeParticipantModel),
        "attendance_scan_batches": AttendanceScanBatchModel,
        "attendance_scan_batch_results": AttendanceScanBatchResultModel,
        "attendance_discard_tombstones": AttendanceDiscardTombstoneModel,
        "identity_notification_outbox": IdentityNotificationOutboxModel,
        "untrusted_upload_scans": UntrustedUploadScanModel,
        "audit_chain_heads": AuditChainHeadModel,
    }

    assert set(created) == set(expected_models)
    for table_name, model in expected_models.items():
        assert _column_names(created[table_name]) == set(model.__table__.columns.keys()), table_name


def test_runtime_discard_and_closeout_constraints_are_database_enforced() -> None:
    _, operation = _run_upgrade()
    created = _created_tables(operation)

    runtime_constraints = _constraint_names(created["attendance_runtime_registrations"])
    assert {
        "fk_attendance_runtime_coordinator_tenant",
        "uq_attendance_runtime_identifier",
        "ck_attendance_runtime_revocation_shape",
        "ck_attendance_runtime_expiry",
    } <= runtime_constraints

    participant_constraints = _constraint_names(created["attendance_session_runtime_participants"])
    assert {
        "fk_attendance_participant_session_tenant",
        "fk_attendance_participant_runtime_tenant_coordinator",
        "uq_attendance_session_runtime_participant",
    } <= participant_constraints

    discard_constraints = _constraint_names(created["attendance_discard_tombstones"])
    assert {
        "fk_attendance_discard_session_tenant_group",
        "fk_attendance_discard_runtime_tenant_coordinator",
        "uq_attendance_discard_event",
        "ck_attendance_discard_scan_reference",
        "ck_attendance_discard_time_order",
    } <= discard_constraints

    batch_constraints = _constraint_names(created["attendance_scan_batches"])
    assert {
        "fk_attendance_scan_batch_session_tenant_group",
        "fk_attendance_scan_batch_runtime_tenant_coordinator",
        "ck_attendance_scan_batch_fingerprint",
        "ck_attendance_scan_batch_item_count",
    } <= batch_constraints

    result_constraints = _constraint_names(created["attendance_scan_batch_results"])
    assert {
        "uq_attendance_scan_batch_result_event",
        "ck_attendance_scan_batch_result_fingerprint",
        "ck_attendance_scan_batch_result_outcome",
        "ck_attendance_scan_batch_result_shape",
    } <= result_constraints

    foreign_key_names = {call.args[0] for call in operation.create_foreign_key.call_args_list}
    assert {
        "fk_attendance_closeout_session_tenant",
        "fk_attendance_closeout_runtime_tenant_coordinator",
        "fk_attendance_record_runtime_tenant_coordinator",
    } <= foreign_key_names

    closeout_indexes = {
        call.args[0]: call
        for call in operation.create_index.call_args_list
        if call.args[1] == "attendance_closeout_checkpoints"
    }
    legacy_index = closeout_indexes["uq_attendance_closeout_legacy_account"]
    assert legacy_index.kwargs["unique"] is True
    assert str(legacy_index.kwargs["postgresql_where"]) == ("runtime_registration_id IS NULL")


def test_legacy_closeout_rows_are_backfilled_before_agency_becomes_required() -> None:
    _, operation = _run_upgrade()
    method_calls = operation.method_calls
    backfill_index = next(
        index
        for index, call in enumerate(method_calls)
        if call[0] == "execute" and "UPDATE attendance_closeout_checkpoints" in str(call.args[0])
    )
    not_null_index = next(
        index
        for index, call in enumerate(method_calls)
        if call[0] == "alter_column"
        and call.args[:2] == ("attendance_closeout_checkpoints", "agency_id")
    )

    assert backfill_index < not_null_index
    assert method_calls[not_null_index].kwargs["nullable"] is False


def test_audit_append_only_and_tamper_evidence_foundation_is_installed() -> None:
    _, operation = _run_upgrade()
    statements = "\n".join(str(call.args[0]) for call in operation.execute.call_args_list)

    assert "CREATE FUNCTION reject_audit_log_mutation" in statements
    assert "CREATE TRIGGER audit_logs_append_only" in statements
    assert "BEFORE UPDATE OR DELETE ON audit_logs" in statements
    assert "ERRCODE = '55000'" in statements

    audit_columns = {
        call.args[1].name
        for call in operation.add_column.call_args_list
        if call.args[0] == "audit_logs"
    }
    assert audit_columns == {
        "result",
        "integrity_version",
        "integrity_scope",
        "integrity_sequence",
        "previous_hash",
        "entry_hash",
    }

    unique_chain_index = next(
        call
        for call in operation.create_index.call_args_list
        if call.args[0] == "uq_audit_logs_integrity_sequence"
    )
    assert unique_chain_index.kwargs["unique"] is True
    assert str(unique_chain_index.kwargs["postgresql_where"]) == ("integrity_version = 1")


def test_downgrade_removes_trigger_before_audit_columns_and_preserves_rows() -> None:
    migration = _load_migration()
    operation = MagicMock()
    migration.op = operation
    migration.downgrade()

    method_calls = operation.method_calls
    drop_trigger_index = next(
        index
        for index, call in enumerate(method_calls)
        if call[0] == "execute" and "DROP TRIGGER" in str(call.args[0])
    )
    first_audit_column_drop = next(
        index
        for index, call in enumerate(method_calls)
        if call[0] == "drop_column" and call.args[0] == "audit_logs"
    )
    assert drop_trigger_index < first_audit_column_drop

    migration_source = MIGRATION_PATH.read_text(encoding="utf-8").lower()
    assert "delete from audit_logs" not in migration_source
    assert "truncate audit_logs" not in migration_source
    assert "my_photos" not in migration_source
    assert "my_photo_" not in migration_source
