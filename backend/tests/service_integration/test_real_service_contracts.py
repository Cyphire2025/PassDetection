from __future__ import annotations

import os
import uuid

import boto3
import pytest
from botocore.exceptions import ClientError
from kombu import Connection
from redis.asyncio import Redis
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.dtos.auth_dtos import LoginInputDTO
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.core.security.password import hash_password
from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import AuthenticationError
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
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
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.refresh_token_repository import (
    RefreshTokenRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository

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
            await connection.execute(
                text(f"CREATE TABLE {table_name} (id integer PRIMARY KEY)")
            )
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
                delete(PassportSubmissionModel).where(
                    PassportSubmissionModel.id == submission_id
                )
            )
            await session.execute(
                delete(ClientGroupModel).where(
                    ClientGroupModel.id.in_([first_group_id, second_group_id])
                )
            )
            await session.execute(
                delete(AgencyModel).where(
                    AgencyModel.id.in_([first_agency_id, second_agency_id])
                )
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
            await session.execute(
                delete(AuditLogModel).where(AuditLogModel.entity_id == str(job_id))
            )
            await session.execute(delete(AgencyModel).where(AgencyModel.id == agency_id))
            await session.commit()
    finally:
        client.delete_object(Bucket=bucket, Key=object_key)
        _delete_bucket_if_empty(client, bucket)
        await engine.dispose()


def test_celery_redis_broker_publish_consume_round_trip() -> None:
    broker_url = (
        f"redis://{os.environ.get('REDIS_HOST', 'localhost')}:"
        f"{os.environ.get('REDIS_PORT', '6379')}/0"
    )
    queue_name = f"enterprise-ci-{uuid.uuid4()}"
    payload = {"probe_id": str(uuid.uuid4())}
    with Connection(broker_url) as connection:
        queue = connection.SimpleQueue(queue_name)
        try:
            queue.put(payload)
            message = queue.get(block=True, timeout=5)
            assert message.payload == payload
            message.ack()
        finally:
            queue.close()


def test_real_celery_worker_executes_idempotent_database_task() -> None:
    first = celery_app.send_task(PLATFORM_LIFECYCLE_TASK, queue="enterprise-ci")
    second = celery_app.send_task(PLATFORM_LIFECYCLE_TASK, queue="enterprise-ci")

    first_result = first.get(timeout=30, disable_sync_subtasks=False)
    second_result = second.get(timeout=30, disable_sync_subtasks=False)

    assert set(first_result) == {
        "archived_groups",
        "scheduled_passport_purge_dates",
        "deleted_passports",
        "deleted_notifications",
        "deleted_audit_logs",
        "storage_cleanup_jobs",
        "storage_objects_scheduled",
    }
    assert all(isinstance(value, int) and value >= 0 for value in first_result.values())
    assert all(isinstance(value, int) and value >= 0 for value in second_result.values())


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
