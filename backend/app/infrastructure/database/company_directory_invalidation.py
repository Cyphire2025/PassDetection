"""Group visibility changes restart only the rebuildable directory checkpoint."""

from sqlalchemy import event, inspect, update
from sqlalchemy.orm import Session

from app.infrastructure.database.company_directory_models import CompanyDirectoryStateModel as State


@event.listens_for(Session, "before_flush")
def remember_directory_groups(session: Session, _context: object, _instances: object) -> None:
    from app.infrastructure.database.models import ClientGroupModel

    scopes = set()
    for row in session.dirty:
        if not isinstance(row, ClientGroupModel):
            continue
        attributes = inspect(row).attrs
        if not any(attributes[key].history.has_changes() for key in ("company_id", "status", "deleted_at")):
            continue
        for company_id in (row.company_id, *attributes.company_id.history.deleted):
            if company_id is not None:
                scopes.add((row.agency_id, company_id))
    if scopes:
        session.info["company_directory_groups"] = scopes


@event.listens_for(Session, "after_flush_postexec")
def invalidate_directory_groups(session: Session, _context: object) -> None:
    for agency_id, company_id in session.info.pop("company_directory_groups", set()):
        session.execute(update(State).where(State.agency_id == agency_id, State.company_id == company_id)
            .values(backfill_after=None, backfill_complete=False, generation=State.generation + 1))
