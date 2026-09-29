"""Synthetic multi-tenant workload fixtures for the fixed local QA stack only.

Creates new records under a random run identifier. Never resets a table, changes
an existing user, contacts a provider, or removes data. Session issuance is a
test fixture, not evidence that authentication was exercised by the load lane.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from capacity_mcp_fixtures import seed_mcp
from PIL import Image
from qualification_application_journey import isolated
from sqlalchemy import func, select, text
from upload_configuration_http_smoke import REQUIRED_FIELD_NAMES

from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.core.config.settings import get_settings
from app.core.security.password import hash_password
from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceRecordModel,
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    NotificationModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.session import AsyncSessionFactory, engine
from app.infrastructure.ecr import ECR_RECOVERY_TASK
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.qr.approved_passenger_qr_issuer import qr_hash
from app.infrastructure.repositories.refresh_token_repository import (
    RefreshTokenRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository

TENANTS = 10
SMALL_GROUP = 100
LARGE_GROUP = 5000


def identifier(run_id: str, name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.UUID(run_id), name)


async def seed(run_id: str) -> dict:
    observed = datetime.now(UTC)
    password_hash = hash_password("Synthetic-only-capacity-account-69371!")
    actors, coordinators, groups = [], [], []
    async with AsyncSessionFactory() as db:
        for tenant in range(TENANTS):
            agency = identifier(run_id, f"agency-{tenant}")
            group_id = identifier(run_id, f"group-{tenant}")
            owner_id = identifier(run_id, f"staff-{tenant}-1")
            size = LARGE_GROUP if tenant == 0 else SMALL_GROUP
            db.add(
                AgencyModel(
                    id=agency,
                    name=f"Synthetic capacity tenant {tenant}",
                    email=f"{run_id}-{tenant}@example.test",
                )
            )
            await db.flush()
            for index in range(3):
                user_id = identifier(run_id, f"staff-{tenant}-{index}")
                role = ("agency_admin", "agency_staff", "agency_coordinator")[index]
                db.add(
                    UserModel(
                        id=user_id,
                        agency_id=agency,
                        email=f"{run_id}-{tenant}-{index}@example.test",
                        full_name="Synthetic capacity operator",
                        role=role,
                        is_active=True,
                        hashed_password=password_hash,
                    )
                )
                await db.flush()
                db.add(
                    UserSecurityStateModel(
                        user_id=user_id,
                        credential_state="active",
                        session_version=1,
                        password_changed_at=observed,
                        mfa_required=False,
                    )
                )
                await db.flush()
                repository = UserRepository(db)
                user = await repository.get_by_id(user_id)
                assert user is not None
                issued = await LoginUseCase(
                    repository, RefreshTokenRepository(db)
                ).issue_session(user)
                actor = {
                    "tenant": tenant,
                    "user_id": str(user_id),
                    "token": issued.access_token,
                    "group_id": str(group_id),
                    "group_size": size,
                    "role": role,
                }
                (actors if index < 2 else coordinators).append(actor)
            db.add(
                ClientGroupModel(
                    id=group_id,
                    agency_id=agency,
                    created_by_user_id=owner_id,
                    name=f"Synthetic capacity roster {tenant}",
                    token=f"capacity-{run_id}-{tenant}",
                    status="active",
                    destination="Synthetic destination",
                    travel_date=observed.date(),
                    return_date=observed.date() + timedelta(days=3),
                )
            )
            await db.flush()
            session_id = identifier(run_id, f"attendance-{tenant}")
            db.add(
                AttendanceSessionModel(
                    id=session_id,
                    canonical_session_id=session_id,
                    agency_id=agency,
                    group_id=group_id,
                    name="Synthetic capacity activity",
                    normalized_name=f"synthetic capacity activity {run_id}",
                    status="active",
                    created_by_user_id=owner_id,
                    started_at=observed - timedelta(minutes=1),
                    scheduled_starts_at=observed - timedelta(hours=1),
                    scheduled_ends_at=observed + timedelta(hours=3),
                    schedule_timezone="Asia/Kolkata",
                    schedule_version=1,
                )
            )
            coordinator = coordinators[-1]
            db.add(
                CoordinatorGroupAssignmentModel(
                    id=uuid.uuid4(),
                    agency_id=agency,
                    group_id=group_id,
                    coordinator_user_id=uuid.UUID(coordinator["user_id"]),
                    assigned_by_user_id=owner_id,
                    active=True,
                )
            )
            coordinator["session_id"] = str(session_id)
            coordinator["qr_payloads"] = []
            for offset in range(0, size, 250):
                for index in range(offset, min(size, offset + 250)):
                    passport = identifier(run_id, f"passenger-{tenant}-{index}")
                    # A skewed duplicate cluster plus unique records exercises
                    # the duplicate-aware prepared view rather than empty data.
                    passport_number = (
                        f"P{tenant:02d}{index:05d}"
                        if index >= 50
                        else f"DUP{tenant:02d}"
                    )
                    db.add(
                        PassportSubmissionModel(
                            id=passport,
                            group_id=group_id,
                            agency_id=agency,
                            client_name=f"Synthetic Traveller {tenant:02d} {index:05d}",
                            image_s3_key=f"qualification/capacity/{run_id}/{passport}.jpg",
                            status="confirmed",
                            confirmed_fields={
                                "passport_number": passport_number,
                                "given_names": f"Synthetic {index}",
                                "surname": f"Traveller {tenant}",
                            },
                        )
                    )
                await db.flush()
            for index in range(min(size, 100)):
                raw = (
                    base64.urlsafe_b64encode(
                        hashlib.sha256(f"{run_id}-{tenant}-{index}".encode()).digest()
                    )
                    .decode()
                    .rstrip("=")
                )
                payload = f"pdatt:{raw}"
                db.add(
                    PassengerQRTokenModel(
                        id=uuid.uuid4(),
                        agency_id=agency,
                        passenger_id=identifier(run_id, f"passenger-{tenant}-{index}"),
                        created_by_user_id=owner_id,
                        token_hash=qr_hash(payload),
                        qr_payload=payload,
                        is_active=True,
                        expires_at=observed + timedelta(days=2),
                    )
                )
                coordinator["qr_payloads"].append(payload)
            for actor in actors[-2:]:
                for index in range(100):
                    db.add(
                        NotificationModel(
                            id=uuid.uuid4(),
                            agency_id=agency,
                            user_id=uuid.UUID(actor["user_id"]),
                            type="capacity_fixture",
                            title="Synthetic notification",
                            message="Synthetic capacity fixture",
                            is_read=False,
                            dedupe_key=f"{run_id}-{index}",
                        )
                    )
            public_id = identifier(run_id, f"public-{tenant}")
            public_token = f"capacity-public-{run_id}-{tenant}"
            db.add(
                ClientGroupModel(
                    id=public_id,
                    agency_id=agency,
                    created_by_user_id=owner_id,
                    name="Synthetic capacity upload",
                    token=public_token,
                    status="active",
                    destination="Synthetic destination",
                    travel_date=observed.date(),
                    return_date=observed.date() + timedelta(days=3),
                    allow_files_from_device=True,
                    require_selfie=False,
                    upload_configuration={
                        "passport_upload_pages": ["cover", "back_cover"],
                        "passport_live_scan": False,
                        "required_fields": {
                            name: False for name in REQUIRED_FIELD_NAMES
                        },
                    },
                )
            )
            groups.append(
                {
                    "tenant": tenant,
                    "agency_id": str(agency),
                    "group_id": str(group_id),
                    "public_token": public_token,
                    "group_size": size,
                }
            )
        await db.commit()
    mcp_actors = await seed_mcp(run_id, groups, password_hash)
    return {
        "run_id": run_id,
        "created_at": observed.isoformat(),
        "actors": actors,
        "coordinators": coordinators,
        "groups": groups,
        "mcp_actors": mcp_actors,
        "dataset": {
            "tenants": TENANTS,
            "office_actors": len(actors),
            "agency_admins": TENANTS,
            "agency_staff": TENANTS,
            "coordinators": len(coordinators),
            "passports": LARGE_GROUP + (TENANTS - 1) * SMALL_GROUP,
            "largest_group": LARGE_GROUP,
            "small_group": SMALL_GROUP,
            "duplicate_cluster_per_group": 50,
            "direct_notification_rows": 2000,
            "external_notification_fanout": 0,
            "mcp_superadmin_actors": len(mcp_actors),
        },
    }


async def queue_retries(run_id: str) -> dict:
    """Real durable failures/recovery with absent images; never invoke external AI."""
    observed = datetime.now(UTC)
    batches = []
    async with AsyncSessionFactory() as db:
        for index in range(100):
            batch_id = uuid.uuid4()
            batches.append(batch_id)
            db.add(
                EcrBatchModel(
                    id=batch_id,
                    agency_id=identifier(run_id, f"agency-{index % TENANTS}"),
                    title=f"capacity-{run_id}",
                    expected_count=1,
                    status="queued",
                    created_at=observed,
                    updated_at=observed - timedelta(minutes=30),
                )
            )
            await db.flush()
            db.add(
                EcrItemModel(
                    id=uuid.uuid4(),
                    batch_id=batch_id,
                    client_id=uuid.uuid4(),
                    original_filename="synthetic-missing.jpg",
                    object_key=None,
                    content_type="image/jpeg",
                    sha256="0" * 64,
                    status="queued",
                    created_at=observed,
                    updated_at=observed,
                )
            )
        await db.commit()
    # Duplicate delivery is deliberate: durable item claims must prevent more
    # than one terminal attempt. Recovery also competes in the general queue.
    task_ids = [
        celery_app.send_task(
            "ecr.process_batch", args=[str(batch)], queue="ecr_checks"
        ).id
        for batch in batches
        for _ in range(3)
    ]
    task_ids += [
        celery_app.send_task(ECR_RECOVERY_TASK, queue="passport_ocr").id
        for _ in range(10)
    ]
    return {
        "durable_jobs": len(batches),
        "deliveries": len(task_ids),
        "external_ai_invoked": False,
    }


async def observe(run_id: str, seconds: int) -> None:
    from redis.asyncio import Redis

    settings = get_settings()
    async with Redis.from_url(settings.redis.broker_url) as redis:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            async with AsyncSessionFactory() as db:
                connections = (
                    await db.execute(
                        text(
                            "SELECT state, wait_event_type, count(*) FROM pg_stat_activity "
                            "GROUP BY state, wait_event_type"
                        )
                    )
                ).all()
                pending, oldest = (
                    await db.execute(
                        select(func.count(), func.min(EcrBatchModel.created_at)).where(
                            EcrBatchModel.title == f"capacity-{run_id}",
                            EcrBatchModel.status.in_(["queued", "processing"]),
                        )
                    )
                ).one()
                maximum = int(await db.scalar(text("SHOW max_connections")))
            memory_file = Path("/sys/fs/cgroup/memory.current")
            queues = {
                name: int(await redis.llen(name))
                for name in ("passport_ocr", "ecr_checks")
            }
            print(
                json.dumps(
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "database_connections": sum(row[2] for row in connections),
                        "database_active": sum(
                            row[2] for row in connections if row[0] == "active"
                        ),
                        "database_lock_waiters": sum(
                            row[2] for row in connections if row[1] == "Lock"
                        ),
                        "database_max_connections": maximum,
                        "queues": queues,
                        "pending_durable_jobs": pending,
                        "oldest_pending_age_seconds": (
                            datetime.now(UTC) - oldest
                        ).total_seconds()
                        if oldest
                        else 0,
                        "backend_cgroup_memory_bytes": int(memory_file.read_text()),
                        "backend_memory_events": {
                            name: int(value) for name, value in (
                                line.split() for line in Path("/sys/fs/cgroup/memory.events").read_text().splitlines()
                            )
                        },
                    }
                ),
                flush=True,
            )
            await asyncio.sleep(2)


async def verify(run_id: str) -> dict:
    async with AsyncSessionFactory() as db:
        rows = (
            await db.execute(
                select(
                    EcrBatchModel.status,
                    EcrItemModel.status,
                    EcrItemModel.reason,
                    EcrItemModel.attempts,
                )
                .join(EcrItemModel, EcrItemModel.batch_id == EcrBatchModel.id)
                .where(EcrBatchModel.title == f"capacity-{run_id}")
            )
        ).all()
        if len(rows) != 100 or any(
            tuple(row) != ("completed_with_errors", "failed", "image_expired", 1)
            for row in rows
        ):
            raise RuntimeError(
                "Retry burst has not settled to exactly one expected durable terminal attempt per item"
            )
        sessions = [
            identifier(run_id, f"attendance-{index}") for index in range(TENANTS)
        ]
        scans = await db.scalar(
            select(func.count())
            .select_from(AttendanceRecordModel)
            .where(AttendanceRecordModel.session_id.in_(sessions))
        )
        uploads = (
            await db.execute(
                select(
                    PassportSubmissionModel.passport_cover_s3_key,
                    PassportSubmissionModel.passport_back_cover_s3_key,
                ).where(
                    PassportSubmissionModel.group_id.in_(
                        [identifier(run_id, f"public-{index}") for index in range(4)]
                    )
                )
            )
        ).all()
    stored_hashes = set()
    storage = MinioStorageRepository()
    for upload in uploads:
        for key in upload:
            if not key:
                raise RuntimeError("A persisted synthetic upload is missing a cover")
            content = await storage.get_file(key)
            with Image.open(io.BytesIO(content)) as cover:
                if cover.size != (1200, 800) or cover.format != "JPEG":
                    raise RuntimeError(
                        "Stored synthetic cover does not match its image contract"
                    )
                cover.verify()
            stored_hashes.add(hashlib.sha256(content).hexdigest())
    return {
        "durable_jobs_verified": len(rows),
        "attempts_per_item": 1,
        "expected_failure_reason": "image_expired",
        "persisted_unique_scans": scans,
        "persisted_uploads": len(uploads),
        "distinct_readable_upload_objects": len(stored_hashes),
    }


async def main() -> None:
    isolated()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["seed", "queues", "observe", "verify"])
    parser.add_argument("run_id")
    parser.add_argument("--seconds", type=int, default=240)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{32}", args.run_id) or not 1 <= args.seconds <= 1800:
        raise RuntimeError("A bounded synthetic run identifier/duration is required")
    try:
        if args.action == "observe":
            await observe(args.run_id, args.seconds)
        else:
            operation = {"seed": seed, "queues": queue_retries, "verify": verify}[
                args.action
            ]
            print(json.dumps(await operation(args.run_id)), flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
