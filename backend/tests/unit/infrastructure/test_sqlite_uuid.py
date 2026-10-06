"""SQLite test schemas must not coerce valid UUIDs into numbers or infinity."""

import uuid

import pytest
from sqlalchemy import UUID, Column, ForeignKey, MetaData, Table, create_engine, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.models import AgencyModel, ClientGroupModel

PATHOLOGICAL_UUIDS = (
    uuid.UUID("00000000-0000-0000-0000-000000000001"),
    uuid.UUID("11111111-1111-4111-8111-111111111111"),
    uuid.UUID("11111111-1111-4111-8111-11111111e999"),
    uuid.UUID("11111111-1111-4111-8111-11111111e001"),
)


@pytest.mark.parametrize("identifier", PATHOLOGICAL_UUIDS)
@pytest.mark.parametrize("as_uuid", (True, False))
def test_sqlite_uuid_round_trip_retains_exact_hex(identifier, as_uuid):
    table = Table("uuid_values", MetaData(), Column("id", UUID(as_uuid=as_uuid), primary_key=True))
    engine = create_engine("sqlite://")
    value = identifier if as_uuid else str(identifier)
    try:
        with engine.begin() as connection:
            table.create(connection)
            connection.execute(table.insert(), {"id": value})
            assert connection.execute(text("SELECT id, typeof(id) FROM uuid_values")).one() == (
                identifier.hex, "text"
            )
            assert connection.scalar(select(table.c.id).where(table.c.id == value)) == value
    finally:
        engine.dispose()


def test_numeric_uuid_keys_remain_distinct_and_foreign_keys_stay_enforced():
    metadata = MetaData()
    parent = Table("uuid_parent", metadata, Column("id", UUID(as_uuid=True), primary_key=True))
    child = Table("uuid_child", metadata, Column("parent_id", UUID(as_uuid=True), ForeignKey(parent.c.id)))
    first = uuid.UUID("11111111-1111-4111-8111-111111111111")
    second = uuid.UUID("11111111-1111-4111-8111-111111111112")
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            metadata.create_all(connection)
            connection.execute(parent.insert(), [{"id": first}, {"id": second}])
            connection.execute(child.insert(), {"parent_id": second})
            assert set(connection.scalars(select(parent.c.id))) == {first, second}
            assert connection.scalar(select(parent.c.id).join(child)) == second
            with pytest.raises(IntegrityError, match="FOREIGN KEY"):
                connection.execute(child.insert(), {"parent_id": uuid.UUID(int=0)})
    finally:
        engine.dispose()


def test_postgresql_models_keep_native_uuid_types():
    for model in (AgencyModel, ClientGroupModel, GCGroupAccessModel):
        assert model.__table__.c.id.type.compile(dialect=postgresql.dialect()) == "UUID"


@pytest.mark.asyncio
async def test_shared_sqlite_fixture_preserves_gc_access_uuid_and_scope(db_session):
    agency_id = PATHOLOGICAL_UUIDS[0]
    group_id = PATHOLOGICAL_UUIDS[1]
    access_id = PATHOLOGICAL_UUIDS[2]
    db_session.add(AgencyModel(id=agency_id, name="UUID fixture", email="uuid@example.test"))
    await db_session.flush()
    db_session.add(ClientGroupModel(id=group_id, agency_id=agency_id, name="Trip", token="uuid-fixture"))
    await db_session.flush()
    db_session.add(GCGroupAccessModel(id=access_id, agency_id=agency_id, group_id=group_id))
    await db_session.flush()
    db_session.expunge_all()

    access = await db_session.scalar(select(GCGroupAccessModel).where(
        GCGroupAccessModel.agency_id == agency_id, GCGroupAccessModel.group_id == group_id
    ))
    assert access is not None
    assert (access.id, access.agency_id, access.group_id) == (access_id, agency_id, group_id)
