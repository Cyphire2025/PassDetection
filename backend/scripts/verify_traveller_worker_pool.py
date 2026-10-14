"""Synthetic PostgreSQL worker admission qualification; never a production probe.

Requires a fresh native_migration database and TRAVELLER_POOL_QUALIFICATION=1.
An explicit expected private host can select a separate synthetic database on a
shared server. Uses no storage/provider calls; the caller owns database cleanup.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import sys
import traceback
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def qualify() -> dict[str, object]:
    if os.environ.get("TRAVELLER_POOL_QUALIFICATION") != "1":
        raise RuntimeError("synthetic_qualification_marker_required")
    from cryptography.fernet import Fernet
    from pydantic import SecretStr
    from sqlalchemy import func, select, text, update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.application.travellers.history_schedule import schedule_group_history
    from app.core.config.settings import DatabaseSettings
    from app.core.config.traveller_reuse import TravellerReuseSettings
    from app.infrastructure.database import model_registry  # noqa: F401
    from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
    from app.infrastructure.database.models import (
        AgencyModel,
        ClientGroupModel,
        PassportSubmissionModel,
        UserModel,
    )
    from app.infrastructure.database.traveller_reuse_models import (
        TravellerChangeEventModel as Event,
    )
    from app.infrastructure.database.traveller_reuse_models import (
        TravellerDocumentRevisionModel as Document,
    )
    from app.infrastructure.database.traveller_reuse_models import (
        TravellerPassportModel as Passport,
    )
    from app.infrastructure.database.traveller_reuse_models import (
        TravellerProfileModel as Person,
    )
    from app.infrastructure.database.traveller_reuse_models import (
        TravellerReconciliationJobModel as Job,
    )
    from app.infrastructure.database.traveller_reuse_models import (
        TravellerReusePolicyModel as Policy,
    )
    from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto
    from app.infrastructure.travellers import impact_runtime, runtime

    settings = DatabaseSettings(password=os.environ["POSTGRES_PASSWORD"])
    expected_host = os.environ.get("TRAVELLER_POOL_QUALIFICATION_HOST", "127.0.0.1")
    address = ipaddress.ip_address(expected_host)
    if not address.is_private or (settings.host, settings.db, settings.port) != (expected_host, "native_migration", 5432):
        raise RuntimeError("synthetic_private_database_required")
    engine = create_async_engine(settings.async_url, pool_size=1, max_overflow=0, pool_timeout=0.5)
    blocker = create_async_engine(settings.async_url, pool_size=1, max_overflow=0, pool_timeout=0.5)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    crypto = TravellerReuseCrypto(TravellerReuseSettings(lookup_key=SecretStr("synthetic-pool-qualification-" * 3),
        encryption_key=SecretStr(Fernet.generate_key().decode())))
    try:
        async with factory() as session, session.begin():
            if await session.scalar(select(func.count()).select_from(AgencyModel)) != 0:
                raise RuntimeError("fresh_synthetic_database_required")
            agency = AgencyModel(name="Synthetic pool qualification", email="pool@example.invalid")
            session.add(agency)
            await session.flush()
            company = ClientOrganizationModel(agency_id=agency.id, name="Synthetic client", normalized_name="synthetic client")
            actor = UserModel(agency_id=agency.id, email="pool-reviewer@example.invalid", full_name="Synthetic reviewer",
                hashed_password="unusable-test-only", role="agency_admin")
            session.add_all([company, actor])
            await session.flush()
            group = ClientGroupModel(agency_id=agency.id, company_id=company.id, company_revision=1,
                token=uuid.uuid4().hex, name="Synthetic historical group")
            session.add(group)
            session.add(Policy(agency_id=agency.id, company_id=company.id, enabled=True,
                configured_by_user_id=actor.id, purpose_version="synthetic", notice_version="synthetic",
                processing_basis="synthetic", configured_at=datetime.now(UTC)))
            await session.flush()
            for index in range(3):
                session.add(PassportSubmissionModel(agency_id=agency.id, group_id=group.id,
                    client_name=f"Synthetic Person {index}", client_phone=f"+91999999999{index}",
                    image_s3_key=f"qualification-only/front-{index}.jpg", status="staff_approved", extraction_revision=1,
                    confirmed_fields={"passport_number": f"90000000{index}", "issuing_country": "IND",
                        "document_type": "PASSPORT", "given_names": "Synthetic", "surname": f"Person {index}",
                        "date_of_birth": "1990-01-01", "date_of_issue": "2020-01-01", "date_of_expiry": "2036-01-01"}))
            await session.flush()
            await schedule_group_history(session, group=group, trigger="synthetic-pool-probe")

        # Both real transaction locks must reject processing, return the lease,
        # and leave the retry budget untouched. The blocker has its own pool.
        async with blocker.connect() as connection, connection.begin():
            for slot in range(2):
                await connection.execute(text("SELECT pg_advisory_xact_lock(913702, :slot)"), {"slot": slot})
            assert await runtime.run_reconciliation_tick(session_factory=factory, crypto=crypto) == 0
        async with factory() as session, session.begin():
            job = await session.scalar(select(Job).where(Job.group_id == group.id, Job.company_id == company.id,
                Job.idempotency_key == "company-group:g:1:1"))
            assert job is not None and (job.status, job.attempt_count, job.lease_expires_at) == ("queued", 0, None)
            job.available_at = datetime.now(UTC) - timedelta(seconds=1)

        async with asyncio.timeout(20):
            processed = await runtime.run_reconciliation_tick(session_factory=factory, crypto=crypto)
        async with factory() as session, session.begin():
            profiles = await session.scalar(select(func.count()).select_from(Person))
            documents = await session.scalar(select(func.count()).select_from(Document))
            job = await session.scalar(select(Job).where(Job.group_id == group.id, Job.company_id == company.id,
                Job.idempotency_key == "company-group:g:1:1"))
            assert processed == 3 and profiles == documents == 3
            assert job is not None and job.status == "succeeded" and job.attempt_count == 0
            # Re-admit the same stable job; stale lease tokens cannot cancel a
            # subsequent owner even when the attempt counter has the same value.
            await schedule_group_history(session, group=group, trigger="synthetic-retry")
        original = await runtime._reserve_reconciliation(factory)
        assert original is not None
        await runtime._release_reconciliation(factory, original)
        async with factory() as session, session.begin():
            job = await session.get(Job, original.job_id)
            assert job is not None
            job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        newer = await runtime._reserve_reconciliation(factory)
        assert newer is not None and newer.lease_expires_at != original.lease_expires_at
        await runtime._release_reconciliation(factory, original)
        await runtime._fail_reconciliation(factory, original)
        async with factory() as session, session.begin():
            job = await session.get(Job, newer.job_id)
            assert job is not None and job.status == "running" and job.lease_expires_at == newer.lease_expires_at
        await runtime._fail_reconciliation(factory, newer)
        async with factory() as session, session.begin():
            job = await session.get(Job, newer.job_id)
            assert job is not None and job.status == "queued" and job.attempt_count == 1
            assert job.last_error_code == "page_processing_failed" and job.lease_expires_at is None
            job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        assert await runtime.run_reconciliation_tick(session_factory=factory, crypto=crypto) == 3

        async with factory() as session, session.begin():
            passport = await session.scalar(select(Passport).limit(1))
            assert passport is not None
            seeded_event = Event(agency_id=agency.id, company_id=company.id, traveller_id=passport.traveller_id,
                event_type="document_blocked", aggregate_id=passport.id, aggregate_revision=1,
                idempotency_key="synthetic-impact-probe", reason_code="synthetic_document_change")
            session.add(seeded_event)
            await session.flush()
            event_id = seeded_event.id
        async with blocker.connect() as connection, connection.begin():
            for slot in range(2):
                await connection.execute(text("SELECT pg_advisory_xact_lock(913703, :slot)"), {"slot": slot})
            assert await impact_runtime.run_impact_tick(session_factory=factory) == 0
        async with factory() as session, session.begin():
            change = await session.get(Event, event_id)
            assert change is not None and change.impact_attempt_count == 0 and change.processed_at is None
            assert await session.scalar(select(func.count()).select_from(Event).where(Event.impact_attempt_count > 0)) == 0
            await session.execute(update(Event).where(Event.processed_at.is_(None)).values(
                impact_available_at=datetime.now(UTC) - timedelta(seconds=1)))
        async with asyncio.timeout(20):
            for _ in range(10):
                await impact_runtime.run_impact_tick(session_factory=factory)
                async with factory() as session:
                    remaining = await session.scalar(select(func.count()).select_from(Event).where(
                        Event.processed_at.is_(None), Event.event_type.in_(("document_promoted", "document_blocked"))))
                if remaining == 0:
                    break
        async with factory() as session, session.begin():
            change = await session.get(Event, event_id)
            assert change is not None and change.processed_at is not None and change.feed_sequence is not None
            assert await session.scalar(select(func.count()).select_from(Person)) == 3
            assert await session.scalar(select(func.count()).select_from(Document)) == 3
        return {"passed": True, "database": "synthetic_test_database", "pool_size": 1, "max_overflow": 0,
            "source_records": 3, "registered_people": profiles, "registered_documents": documents,
            "reconciliation_global_fences": 2, "reconciliation_denied_claim_retry_preserved": True,
            "stale_claim_ignored": True, "durable_failure_retry": True, "impact_and_feed_processed": True,
            "impact_denied_claim_retry_preserved": True, "external_provider_calls": 0}
    finally:
        await engine.dispose()
        await blocker.dispose()


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(qualify()), sort_keys=True))
    except Exception as error:
        # Never print a SQLAlchemy exception, connection URL or bound parameters.
        sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
        if not isinstance(sqlstate, str) or len(sqlstate) != 5 or not sqlstate.isascii() or not sqlstate.isalnum():
            sqlstate = None
        print(json.dumps({"passed": False, "error_type": type(error).__name__, "sqlstate": sqlstate,
            "locations": [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(error.__traceback__)[-8:]]}))
        raise SystemExit(1) from None
