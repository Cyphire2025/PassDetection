"""Transaction-local derived-index admission; no names or source records copied.

Queue rows follow profile/case writes in the same transaction. The consumer locks
company, profile, then queue, so it never blocks a profile writer while retaining
that writer's queue row. Replays collapse to one person and reset controlled retry.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.infrastructure.database import (
    company_directory_invalidation as _invalidation,  # noqa: F401
)
from app.infrastructure.database.company_directory_models import CompanyDirectoryQueueModel as Queue
from app.infrastructure.database.traveller_identity_models import TravellerProfileModel as Person
from app.infrastructure.database.traveller_operations_models import TravellerMatchCaseModel as Case


def queue_directory_rows(session: Session, rows: list[dict[str, Any]], *, reset: bool = True) -> None:
    if not rows:
        return
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    statement = insert(Queue).values(rows)
    statement = (statement.on_conflict_do_update(index_elements=[Queue.traveller_id], set_={
        "available_at": datetime.now(UTC), "attempt_count": 0, "last_error_code": None}) if reset
        else statement.on_conflict_do_nothing(index_elements=[Queue.traveller_id]))
    session.execute(statement)


@event.listens_for(Session, "before_flush")
def remember_directory_changes(session: Session, _flush_context: object, _instances: object) -> None:
    changed = [row for row in session.new.union(session.dirty) if isinstance(row, (Person, Case))]
    if changed:
        session.info["company_directory_changed"] = changed
        session.info["company_directory_prior_people"] = [{"traveller_id": identifier, "agency_id": row.agency_id,
            "company_id": row.company_id, "available_at": datetime.now(UTC), "attempt_count": 0}
            for row in changed if isinstance(row, Case)
            for identifier in inspect(row).attrs.traveller_id.history.deleted if identifier is not None]


@event.listens_for(Session, "after_flush_postexec")
def enqueue_directory_changes(session: Session, _flush_context: object) -> None:
    changed = session.info.pop("company_directory_changed", [])
    people = {row["traveller_id"]: row for row in session.info.pop("company_directory_prior_people", [])}
    for row in changed:
        person_id = row.id if isinstance(row, Person) else row.traveller_id
        if person_id is not None:
            people[person_id] = {"traveller_id": person_id, "agency_id": row.agency_id,
                "company_id": row.company_id, "available_at": datetime.now(UTC), "attempt_count": 0}
    # Existing application writes are already bounded; chunk admission also
    # keeps parameter counts independent of an administrative bulk flush.
    rows = list(people.values())
    for start in range(0, len(rows), 100):
        queue_directory_rows(session, rows[start:start + 100])


@event.listens_for(Session, "after_soft_rollback")
def forget_rolled_back_directory_changes(session: Session, _previous_transaction: object) -> None:
    for key in ("company_directory_changed", "company_directory_prior_people", "company_directory_groups"):
        session.info.pop(key, None)
