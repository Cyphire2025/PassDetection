"""Shared live identity boundary for accepted company and group metrics."""

from sqlalchemy import select
from sqlalchemy.sql.selectable import Exists

from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel,
    TravellerProfileModel,
)


def live_participation_profile() -> Exists:
    """Reuse withdrawal preserves trip history; deleting the identity excludes it."""
    person, participation = TravellerProfileModel, TravellerParticipationModel
    return select(person.id).where(person.id == participation.traveller_id,
        person.agency_id == participation.agency_id, person.company_id == participation.company_id,
        person.deleted_at.is_(None)).correlate(participation).exists()
