from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.repositories.operational_roster import operational_roster_member


async def test_reject_replace_restore_preserves_one_operational_roster_and_history() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine)
    kept, rejected, displaced = (uuid.uuid4() for _ in range(3))
    agency, group = uuid.uuid4(), uuid.uuid4()
    try:
        async with engine.begin() as connection:
            for sql in (
                "CREATE TABLE passport_submissions (id CHAR(32), agency_id CHAR(32), group_id CHAR(32))",
                "CREATE TABLE passport_roster_resolutions (id CHAR(32), agency_id CHAR(32), client_group_id CHAR(32), submission_id CHAR(32), resolution_type TEXT, excluded_submission_ids JSON, status TEXT)",
                "CREATE TABLE attendance_records (passenger_id CHAR(32))",
            ):
                await connection.execute(text(sql))
            for passenger in (kept, rejected, displaced):
                await connection.execute(
                    text("INSERT INTO passport_submissions VALUES (:id,:agency,:group)"),
                    dict(id=passenger.hex, agency=agency.hex, group=group.hex),
                )
                await connection.execute(
                    text("INSERT INTO attendance_records VALUES (:id)"), dict(id=passenger.hex)
                )
            for kind, source, excluded in (
                ("rejected", rejected, []),
                ("replacement", kept, [str(displaced)]),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO passport_roster_resolutions VALUES (:id,:agency,:group,:source,:kind,:excluded,'active')"
                    ),
                    dict(
                        id=uuid.uuid4().hex,
                        agency=agency.hex,
                        group=group.hex,
                        source=source.hex,
                        kind=kind,
                        excluded=json.dumps(excluded),
                    ),
                )
        async with factory() as session:
            query = select(PassportSubmissionModel.id).where(operational_roster_member())
            assert set((await session.scalars(query)).all()) == {kept}
            await session.execute(text("UPDATE passport_roster_resolutions SET status='restored'"))
            await session.commit()
            assert set((await session.scalars(query)).all()) == {kept, rejected, displaced}
            assert await session.scalar(text("SELECT count(*) FROM attendance_records")) == 3
    finally:
        await engine.dispose()


def test_production_predicate_is_tenant_scoped_and_uses_exact_json_membership() -> None:
    sql = str(
        select(PassportSubmissionModel.id)
        .where(operational_roster_member())
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "passport_roster_resolutions.agency_id = passport_submissions.agency_id" in sql
    assert "passport_roster_resolutions.client_group_id = passport_submissions.group_id" in sql
    assert "@> jsonb_build_array" in sql
    assert "'active'" in sql
    assert "NOT (EXISTS" in sql


@pytest.mark.parametrize("scope_column", ["agency_id", "client_group_id"])
async def test_foreign_resolution_cannot_remove_an_authorized_passenger(scope_column: str) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    passenger, agency, group = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE passport_submissions (id CHAR(32), agency_id CHAR(32), group_id CHAR(32))"
                )
            )
            await connection.execute(
                text(
                    "CREATE TABLE passport_roster_resolutions (agency_id CHAR(32), client_group_id CHAR(32), submission_id CHAR(32), resolution_type TEXT, excluded_submission_ids JSON, status TEXT)"
                )
            )
            await connection.execute(
                text("INSERT INTO passport_submissions VALUES (:id,:agency,:group)"),
                dict(id=passenger.hex, agency=agency.hex, group=group.hex),
            )
            await connection.execute(
                text(
                    "INSERT INTO passport_roster_resolutions VALUES (:agency,:group,:id,'rejected','[]','active')"
                ),
                dict(
                    id=passenger.hex,
                    agency=uuid.uuid4().hex if scope_column == "agency_id" else agency.hex,
                    group=uuid.uuid4().hex if scope_column == "client_group_id" else group.hex,
                ),
            )
            assert (
                await connection.execute(
                    select(PassportSubmissionModel.id).where(operational_roster_member())
                )
            ).scalar_one() == passenger
    finally:
        await engine.dispose()
