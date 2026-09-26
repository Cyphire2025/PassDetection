"""Persist explicit synthetic records in database dependency order.

Foreign-key columns do not tell SQLAlchemy's ORM unit of work how to order
unrelated mapped instances. Fixtures without ORM relationships must flush
parent tables first, exactly as production transactions must do.
"""

from collections import defaultdict

from sqlalchemy import inspect

from app.infrastructure.database.models import Base


async def persist_graph(session, records):
    by_table = defaultdict(list)
    for record in records:
        by_table[inspect(record).mapper.local_table.name].append(record)
    for table in Base.metadata.sorted_tables:
        if table.name in by_table:
            session.add_all(by_table.pop(table.name))
            await session.flush()
    if by_table:
        raise AssertionError(f"Unknown fixture tables: {sorted(by_table)}")


async def persist_mobile_access_graph(session, access, records=()):
    """Persist an explicit synthetic mobile scope and its caller-supplied children."""
    from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
    from app.infrastructure.database.models import AgencyModel, ClientGroupModel

    parents = []
    if await session.get(AgencyModel, access.agency_id) is None:
        parents.append(AgencyModel(id=access.agency_id, name="Synthetic agency",
                                   email=f"{access.agency_id}@example.test"))
    if access.client_organization_id and await session.get(ClientOrganizationModel, access.client_organization_id) is None:
        parents.append(ClientOrganizationModel(
            id=access.client_organization_id, agency_id=access.agency_id,
            name="Synthetic company", normalized_name=f"synthetic-{access.client_organization_id}",
        ))
    if await session.get(ClientGroupModel, access.group_id) is None:
        parents.append(ClientGroupModel(id=access.group_id, agency_id=access.agency_id,
                                       name="Synthetic group", token=f"synthetic-{access.group_id}", status="active"))
    await persist_graph(session, [*parents, access, *records])
