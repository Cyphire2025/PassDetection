"""Company reporting follows return dates, independent of upload-link status.

SQL projection stays in the indexed company/group scope; no group history is
hydrated. The final return day remains active in each group's local timezone.
Missing return dates remain active until a return date is recorded.
"""
from datetime import datetime

from sqlalchemy import and_
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.repositories.coordinator_assignment_lifecycle import trip_local_date


def completed_company_trip(now: datetime) -> ColumnElement[bool]:
    return and_(ClientGroupModel.return_date.is_not(None),
                ClientGroupModel.return_date < trip_local_date(now, ClientGroupModel))
