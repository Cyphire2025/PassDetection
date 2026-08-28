from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from botocore.exceptions import ClientError
from kombu import Connection
from redis.asyncio import Redis
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.dtos.auth_dtos import LoginInputDTO
from app.application.use_cases.attendance_dashboard import AttendanceDashboardService
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.core.security.password import hash_password
from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import AuthenticationError
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceCloseoutCheckpointModel,
    AttendanceDiscardTombstoneModel,
    AttendanceRecordModel,
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionModel,
    AttendanceSessionRuntimeParticipantModel,
    AuditLogModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    PassportSubmissionModel,
    RefreshTokenModel,
    UserModel,
)
from app.infrastructure.documents.storage_cleanup import (
    process_storage_cleanup_job,
    stage_storage_cleanup_job,
)
from app.infrastructure.processing.celery_app import (
    PLATFORM_LIFECYCLE_TASK,
    celery_app,
)
from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutCounts,
    AttendanceCloseoutRepository,
)
from app.infrastructure.repositories.attendance_dashboard_repository import (
    AttendanceDashboardRepository,
)
from app.infrastructure.repositories.attendance_discard_repository import (
    AttendanceDiscardInput,
    AttendanceDiscardRepository,
)
from app.infrastructure.repositories.attendance_runtime_repository import (
    AttendanceRuntimeRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.refresh_token_repository import (
    RefreshTokenRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.tour_operations import (
    _insert_canonical_attendance_record,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1",
        reason="requires the isolated enterprise service-integration stack",
    ),
]


def _postgres_url() -> str:
    return (
        "postgresql+asyncpg://"
        f"{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ.get('POSTGRES_HOST', 'localhost')}:"
        f"{os.environ.get('POSTGRES_PORT', '5432')}/"
        f"{os.environ['POSTGRES_DB']}"
    )


@pytest.mark.asyncio
async def test_postgresql_migrations_advisory_locks_and_skip_locked() -> None:
    engine = create_async_engine(_postgres_url(), poolclass=NullPool)
    table_name = f"enterprise_ci_lock_probe_{uuid.uuid4().hex}"
    lock_key = 7_318_224_913
    try:
        async with engine.begin() as connection:
            dialect = await connection.scalar(text("SELECT current_setting('server_version')"))
            assert dialect
            migration_heads = await connection.execute(
                text("SELECT version_num FROM alembic_version")
            )
            assert len(migration_heads.scalars().all()) == 1
            await connection.execute(text(f"CREATE TABLE {table_name} (id integer PRIMARY KEY)"))
            await connection.execute(text(f"INSERT INTO {table_name} (id) VALUES (1)"))

        async with engine.connect() as first, engine.connect() as second:
            first_transaction = await first.begin()
            second_transaction = await second.begin()
            try:
                await first.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
                assert (
                    await second.scalar(
                        text("SELECT pg_try_advisory_xact_lock(:key)"),
                        {"key": lock_key},
                    )
                    is False
                )
                await first.execute(text(f"SELECT id FROM {table_name} FOR UPDATE"))
                skipped = await second.scalar(
                    text(f"SELECT id FROM {table_name} FOR UPDATE SKIP LOCKED")
                )
                assert skipped is None
            finally:
                await second_transaction.rollback()
                await first_transaction.rollback()

        async with engine.begin() as connection:
            assert (
                await connection.scalar(
                    text("SELECT pg_try_advisory_xact_lock(:key)"),
                    {"key": lock_key},
                )
                is True
            )
            await connection.execute(text(f"DROP TABLE {table_name}"))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_redis_round_trip_and_atomic_dedupe() -> None:
    client = Redis(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        decode_responses=True,
    )
    key = f"enterprise-ci:{uuid.uuid4()}"
    try:
        assert await client.ping() is True
        assert await client.set(key, "first", ex=30, nx=True) is True
        assert await client.set(key, "duplicate", ex=30, nx=True) is None
        assert await client.get(key) == "first"
    finally:
        await client.delete(key)
        await client.aclose()


@pytest.mark.asyncio
async def test_real_postgresql_and_redis_authentication_session_contract() -> None:
    engine = create_async_engine(_postgres_url(), poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    agency_id = uuid.uuid4()
    user_id = uuid.uuid4()
    email = f"enterprise-auth-{user_id}@example.com"
    password = "Enterprise-CI-Password-937!"
    try:
        async with session_factory() as session:
            session.add_all(
                [
                    AgencyModel(
                        id=agency_id,
                        name=f"Enterprise Auth {agency_id}",
                        email=f"enterprise-auth-{agency_id}@example.com",
                    ),
                    UserModel(
                        id=user_id,
                        email=email,
                        hashed_password=hash_password(password),
                        full_name="Enterprise Auth Probe",
                        role=UserRole.AGENCY_ADMIN.value,
                        agency_id=agency_id,
                    ),
                ]
            )
            await session.commit()

        async with session_factory() as session:
            use_case = LoginUseCase(
                UserRepository(session),
                RefreshTokenRepository(session),
            )
            try:
                with pytest.raises(AuthenticationError):
                    await use_case.execute(
                        LoginInputDTO(email=email, password="wrong-password"),
                        client_ip="127.0.0.1",
                    )
                result = await use_case.execute(
                    LoginInputDTO(email=email, password=password),
                    client_ip="127.0.0.1",
                )
                await session.commit()
                assert result.user.id == user_id
                assert result.user.agency_id == agency_id
                assert result.access_token
                stored_refresh = await session.scalar(
                    select(RefreshTokenModel).where(RefreshTokenModel.user_id == user_id)
                )
                assert stored_refresh is not None
                assert stored_refresh.token != result.refresh_token
            finally:
                await use_case.aclose()
    finally:
        async with session_factory() as session:
            await session.execute(delete(UserModel).where(UserModel.id == user_id))
            await session.execute(delete(AgencyModel).where(AgencyModel.id == agency_id))
            await session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_postgresql_tenant_contact_scope_uses_advisory_locking() -> None:
    engine = create_async_engine(_postgres_url(), poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    first_agency_id = uuid.uuid4()
    second_agency_id = uuid.uuid4()
    first_group_id = uuid.uuid4()
    second_group_id = uuid.uuid4()
    submission_id = uuid.uuid4()
    email = f"tenant-probe-{submission_id}@example.com"
    try:
        async with session_factory() as session:
            session.add_all(
                [
                    AgencyModel(
                        id=first_agency_id,
                        name=f"Tenant Probe A {first_agency_id}",
                        email=f"tenant-a-{first_agency_id}@example.com",
                    ),
                    AgencyModel(
                        id=second_agency_id,
                        name=f"Tenant Probe B {second_agency_id}",
                        email=f"tenant-b-{second_agency_id}@example.com",
                    ),
                    ClientGroupModel(
                        id=first_group_id,
                        name="Tenant Probe A",
                        token=f"tenant-a-{uuid.uuid4()}",
                        agency_id=first_agency_id,
                        status="active",
                        created_by_user_id=None,
                    ),
                    ClientGroupModel(
                        id=second_group_id,
                        name="Tenant Probe B",
                        token=f"tenant-b-{uuid.uuid4()}",
                        agency_id=second_agency_id,
                        status="active",
                        created_by_user_id=None,
                    ),
                    PassportSubmissionModel(
                        id=submission_id,
                        group_id=first_group_id,
                        agency_id=first_agency_id,
                        client_name="Tenant A Passenger",
                        client_email=email,
                        image_s3_key=f"front/tenant-{submission_id}.jpg",
                    ),
                ]
            )
            await session.commit()

        async with session_factory() as session:
            repository = PassportSubmissionRepository(session)
            assert await repository.exists_contact_in_group(
                first_group_id,
                client_email=email,
                client_phone=None,
                scope="group",
            )
            assert not await repository.exists_contact_in_group(
                second_group_id,
                client_email=email,
                client_phone=None,
                scope="group",
            )
            assert await repository.exists_contact_in_group(
                second_group_id,
                client_email=email,
                client_phone=None,
                scope="platform",
            )
            await session.rollback()
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(PassportSubmissionModel).where(PassportSubmissionModel.id == submission_id)
            )
            await session.execute(
                delete(ClientGroupModel).where(
                    ClientGroupModel.id.in_([first_group_id, second_group_id])
                )
            )
            await session.execute(
                delete(AgencyModel).where(AgencyModel.id.in_([first_agency_id, second_agency_id]))
            )
            await session.commit()
        await engine.dispose()


def test_real_minio_private_object_round_trip() -> None:
    endpoint = os.environ["S3_ENDPOINT_URL"]
    access_key = os.environ["S3_ACCESS_KEY_ID"]
    secret_key = os.environ["S3_SECRET_ACCESS_KEY"]
    bucket = os.environ["S3_BUCKET_NAME"]
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    key = f"enterprise-ci/{uuid.uuid4()}.txt"
    _ensure_bucket(client, bucket)
    try:
        client.put_object(Bucket=bucket, Key=key, Body=b"service-contract")
        response = client.get_object(Bucket=bucket, Key=key)
        assert response["Body"].read() == b"service-contract"
        listing = client.list_objects_v2(Bucket=bucket, Prefix="enterprise-ci/")
        assert key in {item["Key"] for item in listing.get("Contents", [])}
    finally:
        client.delete_object(Bucket=bucket, Key=key)
        _delete_bucket_if_empty(client, bucket)


@pytest.mark.asyncio
async def test_real_postgresql_minio_deletion_tombstone_is_audited_and_idempotent() -> None:
    endpoint = os.environ["S3_ENDPOINT_URL"]
    bucket = os.environ["S3_BUCKET_NAME"]
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        region_name="us-east-1",
    )
    _ensure_bucket(client, bucket)
    agency_id = uuid.uuid4()
    object_key = f"front/enterprise-ci-{uuid.uuid4()}.jpg"
    engine = create_async_engine(_postgres_url(), poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    job_id: uuid.UUID | None = None
    try:
        client.put_object(Bucket=bucket, Key=object_key, Body=b"sensitive-fixture")
        async with session_factory() as session:
            session.add(
                AgencyModel(
                    id=agency_id,
                    name=f"Cleanup Probe {agency_id}",
                    email=f"cleanup-{agency_id}@example.com",
                )
            )
            await session.flush()
            job = stage_storage_cleanup_job(
                session,
                agency_id=agency_id,
                source="passport_submission_delete",
                context_id=f"enterprise-ci:{agency_id}",
                storage_keys=[object_key],
            )
            assert job is not None
            job_id = job.id
            await session.commit()

        result = await process_storage_cleanup_job(
            job_id,
            session_factory=session_factory,
            storage_factory=MinioStorageRepository,
        )
        assert result is not None and result.completed is True
        assert result.deleted_count == 1
        assert (
            await process_storage_cleanup_job(
                job_id,
                session_factory=session_factory,
                storage_factory=MinioStorageRepository,
            )
        ) is None
        with pytest.raises(ClientError) as missing:
            client.head_object(Bucket=bucket, Key=object_key)
        assert missing.value.response["Error"]["Code"] in {"404", "NoSuchKey"}

        async with session_factory() as session:
            audit = await session.scalar(
                select(AuditLogModel).where(
                    AuditLogModel.action == "document_storage_cleanup_completed",
                    AuditLogModel.entity_id == str(job_id),
                )
            )
            assert audit is not None
            assert audit.metadata_json["object_count"] == 1
            # Audit evidence intentionally survives fixture teardown. Revision
            # 0087 rejects ordinary UPDATE/DELETE statements at the database
            # layer and removes the source-account foreign keys for this case.
            await session.execute(delete(AgencyModel).where(AgencyModel.id == agency_id))
            await session.commit()
    finally:
        client.delete_object(Bucket=bucket, Key=object_key)
        _delete_bucket_if_empty(client, bucket)
        await engine.dispose()


@pytest.mark.asyncio
async def test_enterprise_schema_and_append_only_audit_are_enforced_by_postgresql() -> None:
    engine = create_async_engine(_postgres_url(), poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    audit_id = uuid.uuid4()
    try:
        async with engine.connect() as connection:
            columns = (
                await connection.execute(
                    text(
                        """
                        SELECT table_name, column_name
                          FROM information_schema.columns
                         WHERE table_schema = current_schema()
                           AND table_name IN (
                               'attendance_runtime_registrations',
                               'attendance_session_runtime_participants',
                               'attendance_discard_tombstones',
                               'identity_notification_outbox',
                               'untrusted_upload_scans',
                               'audit_chain_heads',
                               'audit_logs'
                           )
                        """
                    )
                )
            ).all()
            by_table: dict[str, set[str]] = {}
            for table_name, column_name in columns:
                by_table.setdefault(table_name, set()).add(column_name)

            assert "updated_at" in by_table["attendance_discard_tombstones"]
            assert {
                "runtime_registration_id",
                "discard_event_id",
                "scan_reference",
                "retention_expires_at",
            } <= by_table["attendance_discard_tombstones"]
            assert {
                "integrity_version",
                "integrity_scope",
                "integrity_sequence",
                "previous_hash",
                "entry_hash",
                "result",
            } <= by_table["audit_logs"]
            trigger_enabled = await connection.scalar(
                text(
                    """
                    SELECT tgenabled::text
                      FROM pg_trigger
                     WHERE tgrelid = 'audit_logs'::regclass
                       AND tgname = 'audit_logs_append_only'
                       AND NOT tgisinternal
                    """
                )
            )
            assert trigger_enabled == "O"

        async with session_factory() as session:
            session.add(
                AuditLogModel(
                    id=audit_id,
                    action="enterprise.schema_probe",
                    entity_type="service_integration",
                    entity_id=str(audit_id),
                    result="success",
                    metadata_json={"fixture": "privacy-safe"},
                    created_at=datetime.now(tz=UTC),
                )
            )
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(DBAPIError) as update_failure:
                await session.execute(
                    update(AuditLogModel)
                    .where(AuditLogModel.id == audit_id)
                    .values(result="failed")
                )
            assert getattr(update_failure.value.orig, "sqlstate", None) == "55000"
            await session.rollback()

        async with session_factory() as session:
            with pytest.raises(DBAPIError) as delete_failure:
                await session.execute(delete(AuditLogModel).where(AuditLogModel.id == audit_id))
            assert getattr(delete_failure.value.orig, "sqlstate", None) == "55000"
            await session.rollback()

        async with session_factory() as session:
            retained = await session.get(AuditLogModel, audit_id)
            assert retained is not None
            assert retained.result == "success"
            assert retained.metadata_json == {"fixture": "privacy-safe"}
    finally:
        # The append-only privacy-safe probe is deliberate retained evidence.
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_runtime_discard_idempotency_tenant_isolation_and_multidevice_closeout() -> None:
    engine = create_async_engine(_postgres_url(), poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    observed = datetime.now(tz=UTC)
    agency_id = uuid.uuid4()
    other_agency_id = uuid.uuid4()
    coordinator_id = uuid.uuid4()
    group_id = uuid.uuid4()
    attendance_session_id = uuid.uuid4()
    event_id = uuid.uuid4()
    scan_reference = "a" * 64
    runtime_ids: list[uuid.UUID] = []
    try:
        async with session_factory() as session:
            session.add_all(
                [
                    AgencyModel(
                        id=agency_id,
                        name=f"Runtime Probe {agency_id}",
                        email=f"runtime-{agency_id}@example.com",
                    ),
                    AgencyModel(
                        id=other_agency_id,
                        name=f"Other Runtime Probe {other_agency_id}",
                        email=f"runtime-{other_agency_id}@example.com",
                    ),
                    UserModel(
                        id=coordinator_id,
                        email=f"runtime-coordinator-{coordinator_id}@example.com",
                        hashed_password=hash_password("Runtime-Probe-Password-937!"),
                        full_name="Shared Runtime Coordinator",
                        role=UserRole.AGENCY_COORDINATOR.value,
                        agency_id=agency_id,
                    ),
                ]
            )
            await session.flush()
            session.add(
                ClientGroupModel(
                    id=group_id,
                    name="Runtime Probe Group",
                    token=f"runtime-probe-{uuid.uuid4()}",
                    agency_id=agency_id,
                    status="active",
                    created_by_user_id=coordinator_id,
                )
            )
            await session.flush()
            session.add_all(
                [
                    CoordinatorGroupAssignmentModel(
                        id=uuid.uuid4(),
                        agency_id=agency_id,
                        group_id=group_id,
                        coordinator_user_id=coordinator_id,
                        assigned_by_user_id=coordinator_id,
                        active=True,
                        assigned_at=observed - timedelta(hours=2),
                    ),
                    AttendanceSessionModel(
                        id=attendance_session_id,
                        agency_id=agency_id,
                        group_id=group_id,
                        name="Runtime Probe Activity",
                        normalized_name="runtime probe activity",
                        canonical_session_id=attendance_session_id,
                        status="active",
                        created_by_user_id=coordinator_id,
                        created_at=observed - timedelta(hours=1),
                        updated_at=observed,
                        started_at=observed - timedelta(hours=1),
                    ),
                ]
            )
            await session.commit()

        async with session_factory() as session:
            runtime_repository = AttendanceRuntimeRepository(session)
            first_runtime = await runtime_repository.register(
                agency_id=agency_id,
                coordinator_user_id=coordinator_id,
                runtime_kind="native_mobile",
                runtime_identifier=f"first-{uuid.uuid4()}",
                expires_at=observed + timedelta(days=30),
                now=observed,
            )
            second_runtime = await runtime_repository.register(
                agency_id=agency_id,
                coordinator_user_id=coordinator_id,
                runtime_kind="native_mobile",
                runtime_identifier=f"second-{uuid.uuid4()}",
                expires_at=observed + timedelta(days=30),
                now=observed,
            )
            runtime_ids.extend([first_runtime.id, second_runtime.id])
            closeout = AttendanceCloseoutRepository(session)
            await closeout.publish(
                agency_id=agency_id,
                session_id=attendance_session_id,
                coordinator_user_id=coordinator_id,
                runtime_registration_id=first_runtime.id,
                counts=AttendanceCloseoutCounts(0, 0, 0, 0, 0, None),
                reported_at=observed,
            )
            await closeout.publish(
                agency_id=agency_id,
                session_id=attendance_session_id,
                coordinator_user_id=coordinator_id,
                runtime_registration_id=second_runtime.id,
                counts=AttendanceCloseoutCounts(3, 0, 0, 0, 0, 30),
                reported_at=observed,
            )
            await session.commit()

        async with session_factory() as session:
            blocked = await AttendanceCloseoutRepository(session).status(
                agency_id=agency_id,
                group_id=group_id,
                session_id=attendance_session_id,
                activity_valid_after=observed - timedelta(hours=1),
                now=observed + timedelta(seconds=1),
            )
            assert blocked.ready is False
            assert blocked.active_assignment_count == 2
            assert blocked.ready_assignment_count == 1
            assert blocked.blocked_assignment_count == 1
            assert blocked.unresolved_count == 3

        async def deliver_discard() -> str:
            async with session_factory() as session:
                result = await AttendanceDiscardRepository(session).record_batch(
                    agency_id=agency_id,
                    group_id=group_id,
                    session_id=attendance_session_id,
                    coordinator_user_id=coordinator_id,
                    runtime_registration_id=runtime_ids[1],
                    items=(
                        AttendanceDiscardInput(
                            discard_event_id=event_id,
                            scan_reference=scan_reference,
                            reason_category="server_terminal_rejection",
                            captured_at=observed - timedelta(minutes=2),
                            discarded_at=observed - timedelta(minutes=1),
                        ),
                    ),
                    retention_days=365,
                    now=observed,
                )
                await session.commit()
                return result[0].status

        deliveries = await asyncio.gather(deliver_discard(), deliver_discard())
        assert sorted(deliveries) == ["accepted", "already_applied"]

        async with session_factory() as session:
            receipt_count = await session.scalar(
                select(func.count(AttendanceDiscardTombstoneModel.id)).where(
                    AttendanceDiscardTombstoneModel.agency_id == agency_id,
                    AttendanceDiscardTombstoneModel.coordinator_user_id == coordinator_id,
                    AttendanceDiscardTombstoneModel.discard_event_id == event_id,
                )
            )
            assert receipt_count == 1

            session.add(
                AttendanceDiscardTombstoneModel(
                    id=uuid.uuid4(),
                    agency_id=other_agency_id,
                    group_id=group_id,
                    session_id=attendance_session_id,
                    coordinator_user_id=coordinator_id,
                    runtime_registration_id=runtime_ids[0],
                    discard_event_id=uuid.uuid4(),
                    scan_reference="b" * 64,
                    reason_category="other",
                    discarded_at=observed - timedelta(minutes=1),
                    received_at=observed,
                    status="accepted",
                    retention_expires_at=observed + timedelta(days=365),
                    updated_at=observed,
                )
            )
            with pytest.raises(IntegrityError) as tenant_failure:
                await session.flush()
            assert getattr(tenant_failure.value.orig, "sqlstate", None) == "23503"
            await session.rollback()

        async with session_factory() as session:
            await AttendanceCloseoutRepository(session).publish(
                agency_id=agency_id,
                session_id=attendance_session_id,
                coordinator_user_id=coordinator_id,
                runtime_registration_id=runtime_ids[1],
                counts=AttendanceCloseoutCounts(0, 0, 0, 0, 0, None),
                reported_at=observed + timedelta(seconds=2),
            )
            await session.commit()

        async with session_factory() as session:
            ready = await AttendanceCloseoutRepository(session).status(
                agency_id=agency_id,
                group_id=group_id,
                session_id=attendance_session_id,
                activity_valid_after=observed - timedelta(hours=1),
                now=observed + timedelta(seconds=3),
            )
            assert ready.ready is True
            assert ready.active_assignment_count == 2
            assert ready.ready_assignment_count == 2
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(AttendanceDiscardTombstoneModel).where(
                    AttendanceDiscardTombstoneModel.agency_id == agency_id
                )
            )
            await session.execute(
                delete(AttendanceCloseoutCheckpointModel).where(
                    AttendanceCloseoutCheckpointModel.agency_id == agency_id
                )
            )
            await session.execute(
                delete(AttendanceSessionRuntimeParticipantModel).where(
                    AttendanceSessionRuntimeParticipantModel.agency_id == agency_id
                )
            )
            await session.execute(
                delete(AttendanceRuntimeRegistrationModel).where(
                    AttendanceRuntimeRegistrationModel.agency_id == agency_id
                )
            )
            await session.execute(
                delete(CoordinatorGroupAssignmentModel).where(
                    CoordinatorGroupAssignmentModel.agency_id == agency_id
                )
            )
            await session.execute(
                delete(AttendanceSessionModel).where(AttendanceSessionModel.agency_id == agency_id)
            )
            await session.execute(
                delete(ClientGroupModel).where(ClientGroupModel.agency_id == agency_id)
            )
            await session.execute(delete(UserModel).where(UserModel.id == coordinator_id))
            await session.execute(
                delete(AgencyModel).where(AgencyModel.id.in_([agency_id, other_agency_id]))
            )
            await session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_25_coordinator_800_passenger_attendance_burst_and_convergence() -> None:
    engine = create_async_engine(_postgres_url(), poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    observed = datetime.now(tz=UTC)
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    attendance_session_id = uuid.uuid4()
    coordinator_ids = [uuid.uuid4() for _ in range(25)]
    passenger_ids = [uuid.uuid4() for _ in range(800)]
    password_hash = hash_password("Attendance-Load-Probe-937!")
    try:
        async with session_factory() as session:
            session.add(
                AgencyModel(
                    id=agency_id,
                    name=f"Attendance Load {agency_id}",
                    email=f"attendance-load-{agency_id}@example.com",
                )
            )
            session.add_all(
                [
                    UserModel(
                        id=coordinator_id,
                        email=f"attendance-load-{coordinator_id}@example.com",
                        hashed_password=password_hash,
                        full_name=f"Load Coordinator {index + 1}",
                        role=UserRole.AGENCY_COORDINATOR.value,
                        agency_id=agency_id,
                    )
                    for index, coordinator_id in enumerate(coordinator_ids)
                ]
            )
            await session.flush()
            session.add(
                ClientGroupModel(
                    id=group_id,
                    name="800 Passenger Load Probe",
                    token=f"attendance-load-{uuid.uuid4()}",
                    agency_id=agency_id,
                    status="active",
                    created_by_user_id=coordinator_ids[0],
                )
            )
            await session.flush()
            session.add_all(
                [
                    PassportSubmissionModel(
                        id=passenger_id,
                        group_id=group_id,
                        agency_id=agency_id,
                        client_name=f"Load Passenger {index + 1:04d}",
                        image_s3_key=f"enterprise-load/{passenger_id}.jpg",
                        status="confirmed",
                    )
                    for index, passenger_id in enumerate(passenger_ids)
                ]
            )
            session.add_all(
                [
                    CoordinatorGroupAssignmentModel(
                        id=uuid.uuid4(),
                        agency_id=agency_id,
                        group_id=group_id,
                        coordinator_user_id=coordinator_id,
                        assigned_by_user_id=coordinator_ids[0],
                        active=True,
                        assigned_at=observed - timedelta(hours=2),
                    )
                    for coordinator_id in coordinator_ids
                ]
            )
            session.add(
                AttendanceSessionModel(
                    id=attendance_session_id,
                    agency_id=agency_id,
                    group_id=group_id,
                    name="Bursty Arrival",
                    normalized_name="bursty arrival",
                    canonical_session_id=attendance_session_id,
                    status="active",
                    created_by_user_id=coordinator_ids[0],
                    created_at=observed - timedelta(hours=1),
                    updated_at=observed,
                    started_at=observed - timedelta(hours=1),
                )
            )
            await session.commit()

        async def synchronize_partition(coordinator_index: int) -> int:
            coordinator_id = coordinator_ids[coordinator_index]
            inserted = 0
            async with session_factory() as session:
                attendance_session = await session.get(
                    AttendanceSessionModel,
                    attendance_session_id,
                )
                assert attendance_session is not None
                for passenger_index in range(coordinator_index, 800, 25):
                    passenger_id = passenger_ids[passenger_index]
                    client_event_id = f"load:{passenger_index:04d}"
                    first = await _insert_canonical_attendance_record(
                        session=session,
                        agency_id=agency_id,
                        attendance_session=attendance_session,
                        passenger_id=passenger_id,
                        coordinator_user_id=coordinator_id,
                        scanned_at=observed - timedelta(minutes=30),
                        sync_source=("offline" if passenger_index % 3 == 0 else "online"),
                        client_event_id=client_event_id,
                        device_id=f"runtime:{coordinator_index:02d}",
                    )
                    duplicate = await _insert_canonical_attendance_record(
                        session=session,
                        agency_id=agency_id,
                        attendance_session=attendance_session,
                        passenger_id=passenger_id,
                        coordinator_user_id=coordinator_id,
                        scanned_at=observed - timedelta(minutes=30),
                        sync_source=("offline" if passenger_index % 3 == 0 else "online"),
                        client_event_id=client_event_id,
                        device_id=f"runtime:{coordinator_index:02d}",
                    )
                    inserted += int(first is not None)
                    assert duplicate is None
                await session.commit()
            return inserted

        burst_started = time.perf_counter()
        inserted_counts = await asyncio.gather(
            *(synchronize_partition(index) for index in range(25))
        )
        burst_seconds = time.perf_counter() - burst_started
        assert sum(inserted_counts) == 800

        async def publish_closeout(coordinator_index: int) -> None:
            pending = 4 if coordinator_index == 24 else 0
            async with session_factory() as session:
                await AttendanceCloseoutRepository(session).publish(
                    agency_id=agency_id,
                    session_id=attendance_session_id,
                    coordinator_user_id=coordinator_ids[coordinator_index],
                    counts=AttendanceCloseoutCounts(
                        pending,
                        0,
                        0,
                        0,
                        0,
                        15 if pending else None,
                    ),
                    reported_at=observed,
                )
                await session.commit()

        await asyncio.gather(*(publish_closeout(index) for index in range(25)))

        async with session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count(AttendanceRecordModel.id)).where(
                        AttendanceRecordModel.agency_id == agency_id,
                        AttendanceRecordModel.session_id == attendance_session_id,
                    )
                )
            ) == 800
            assert (
                await session.scalar(
                    select(func.count(func.distinct(AttendanceRecordModel.passenger_id))).where(
                        AttendanceRecordModel.agency_id == agency_id,
                        AttendanceRecordModel.session_id == attendance_session_id,
                    )
                )
            ) == 800

        statements: list[str] = []

        def count_statement(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", count_statement)
        try:
            async with session_factory() as session:
                service = AttendanceDashboardService(
                    AttendanceDashboardRepository(session),
                    AttendanceCloseoutRepository(session),
                )
                blocked_summary = await service.summary(
                    agency_id=agency_id,
                    group_id=group_id,
                    group_name="800 Passenger Load Probe",
                )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count_statement)

        # Three aggregate queries, three closeout/runtime projections, and one
        # bounded coordinator scan aggregation. Query count must stay constant
        # as coordinators and passengers grow.
        normalized_statements = [statement.lower() for statement in statements]
        assert (
            sum(
                "attendance_session_runtime_participants" in statement
                for statement in normalized_statements
            )
            == 1
        )
        assert (
            sum(
                "attendance_coordinator_scan_family" in statement
                for statement in normalized_statements
            )
            == 1
        )
        assert len(statements) == 7
        assert blocked_summary.activities[0].present_count == 800
        assert blocked_summary.activities[0].missing_count == 0
        assert blocked_summary.activities[0].closeout.ready is False
        assert blocked_summary.activities[0].closeout.active_participant_count == 25
        assert blocked_summary.activities[0].closeout.blocked_participant_count == 1
        normalized_sql = "\n".join(normalized_statements)
        assert "passport_submissions.client_name" not in normalized_sql
        assert "passport_submissions.client_email" not in normalized_sql
        assert "passport_submissions.client_phone" not in normalized_sql

        async with session_factory() as session:
            await AttendanceCloseoutRepository(session).publish(
                agency_id=agency_id,
                session_id=attendance_session_id,
                coordinator_user_id=coordinator_ids[24],
                counts=AttendanceCloseoutCounts(0, 0, 0, 0, 0, None),
                reported_at=observed + timedelta(seconds=1),
            )
            await session.commit()

        convergence_started = time.perf_counter()
        async with session_factory() as session:
            final_summary = await AttendanceDashboardService(
                AttendanceDashboardRepository(session),
                AttendanceCloseoutRepository(session),
            ).summary(
                agency_id=agency_id,
                group_id=group_id,
                group_name="800 Passenger Load Probe",
            )
        convergence_seconds = time.perf_counter() - convergence_started
        convergence_budget = float(os.getenv("ATTENDANCE_CONVERGENCE_BUDGET_SECONDS", "5"))
        assert convergence_seconds <= convergence_budget
        assert final_summary.activities[0].present_count == 800
        assert final_summary.activities[0].missing_count == 0
        assert final_summary.activities[0].closeout.ready is True
        assert final_summary.activities[0].closeout.ready_participant_count == 25

        summary_payload = json.dumps(
            {
                "group_id": str(final_summary.group_id),
                "group_name": final_summary.group_name,
                "revision": final_summary.revision,
                "sessions": [
                    {
                        "id": str(item.session_id),
                        "revision": item.revision,
                        "present_count": item.present_count,
                        "missing_count": item.missing_count,
                        "exception_count": item.exception_count,
                        "closeout_ready": item.closeout.ready,
                        "last_canonical_update_at": (item.last_canonical_update_at.isoformat()),
                    }
                    for item in final_summary.activities
                ],
            },
            separators=(",", ":"),
        )
        full_roster_payload = json.dumps(
            [
                {"id": str(passenger_id), "name": f"Load Passenger {index + 1:04d}"}
                for index, passenger_id in enumerate(passenger_ids)
            ],
            separators=(",", ":"),
        )
        assert len(summary_payload.encode("utf-8")) < 1_500
        assert len(full_roster_payload.encode("utf-8")) > (
            len(summary_payload.encode("utf-8")) * 100
        )
        print(
            "attendance_workload_metrics "
            f"coordinators=25 passengers=800 canonical_records=800 "
            f"duplicate_attempts=800 summary_queries={len(statements)} "
            f"burst_seconds={burst_seconds:.3f} "
            f"convergence_seconds={convergence_seconds:.3f} "
            f"summary_bytes={len(summary_payload.encode('utf-8'))} "
            f"full_roster_bytes={len(full_roster_payload.encode('utf-8'))}"
        )
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(AttendanceCloseoutCheckpointModel).where(
                    AttendanceCloseoutCheckpointModel.agency_id == agency_id
                )
            )
            await session.execute(
                delete(AttendanceRecordModel).where(AttendanceRecordModel.agency_id == agency_id)
            )
            await session.execute(
                delete(CoordinatorGroupAssignmentModel).where(
                    CoordinatorGroupAssignmentModel.agency_id == agency_id
                )
            )
            await session.execute(
                delete(AttendanceSessionModel).where(AttendanceSessionModel.agency_id == agency_id)
            )
            await session.execute(
                delete(PassportSubmissionModel).where(
                    PassportSubmissionModel.agency_id == agency_id
                )
            )
            await session.execute(
                delete(ClientGroupModel).where(ClientGroupModel.agency_id == agency_id)
            )
            await session.execute(delete(UserModel).where(UserModel.id.in_(coordinator_ids)))
            await session.execute(delete(AgencyModel).where(AgencyModel.id == agency_id))
            await session.commit()
        await engine.dispose()


def test_celery_redis_broker_publish_consume_round_trip() -> None:
    broker_url = (
        f"redis://{os.environ.get('REDIS_HOST', 'localhost')}:"
        f"{os.environ.get('REDIS_PORT', '6379')}/0"
    )
    queue_name = f"enterprise-ci-{uuid.uuid4()}"
    payload = {"probe_id": str(uuid.uuid4())}
    with Connection(broker_url) as connection:
        channel = connection.channel()
        queue = connection.SimpleQueue(queue_name, channel=channel)
        try:
            queue.put(payload)
            message = queue.get(block=True, timeout=5)
            assert message.payload == payload
            message.ack()
        finally:
            queue.close()
            channel.close()


def test_real_celery_worker_executes_idempotent_database_task() -> None:
    first = celery_app.send_task(PLATFORM_LIFECYCLE_TASK, queue="enterprise-ci")
    second = celery_app.send_task(PLATFORM_LIFECYCLE_TASK, queue="enterprise-ci")

    first_result = first.get(timeout=30, disable_sync_subtasks=False)
    second_result = second.get(timeout=30, disable_sync_subtasks=False)

    expected_result_fields = {
        "archived_groups",
        "scheduled_passport_purge_dates",
        "deleted_passports",
        "deleted_notifications",
        "deleted_audit_logs",
        "storage_cleanup_jobs",
        "storage_objects_scheduled",
        "expired_runtimes",
        "deleted_runtime_registrations",
        "deleted_discard_tombstones",
        "deleted_upload_scan_records",
        "quarantine_cleanup_jobs",
        "quarantine_objects_scheduled",
        "quarantine_locator_failures",
    }
    assert set(first_result) == expected_result_fields
    assert set(second_result) == expected_result_fields
    assert all(isinstance(value, int) and value >= 0 for value in first_result.values())
    assert all(isinstance(value, int) and value >= 0 for value in second_result.values())
    assert first_result["deleted_audit_logs"] == 0
    assert second_result["deleted_audit_logs"] == 0


def _ensure_bucket(client: object, bucket: str) -> None:
    try:
        client.create_bucket(Bucket=bucket)  # type: ignore[attr-defined]
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {
            "BucketAlreadyOwnedByYou",
            "BucketAlreadyExists",
        }:
            raise


def _delete_bucket_if_empty(client: object, bucket: str) -> None:
    listing = client.list_objects_v2(Bucket=bucket)  # type: ignore[attr-defined]
    if not listing.get("Contents"):
        client.delete_bucket(Bucket=bucket)  # type: ignore[attr-defined]
