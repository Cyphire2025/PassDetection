"""Authoritative reviewed dates and deterministic current-passport promotion."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.services.traveller_verification import parse_answer
from app.domain.value_objects.passport_fields import normalize_passport_date
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel,
    TravellerPassportModel,
    TravellerProfileModel,
)


class EnrollmentError(ValueError):
    """Safe reason code; callers must not include source field values."""


def accepted_dates(fields: dict[str, str]) -> dict[str, date]:
    values: dict[str, date] = {}
    for key, source_key in (("date_of_birth", "date_of_birth"), ("issue_date", "date_of_issue"), ("expiry_date", "date_of_expiry")):
        raw = fields.get(source_key) or fields.get(key)
        if raw:
            try:
                values[key] = parse_answer(normalize_passport_date(raw, field=source_key))
            except ValueError as exc:
                raise EnrollmentError("invalid_accepted_date") from exc
    if values.get("issue_date") and values.get("expiry_date") and values["expiry_date"] < values["issue_date"]:
        raise EnrollmentError("invalid_accepted_date")
    return values



async def promote_default(
    session: AsyncSession, person: TravellerProfileModel, passport: TravellerPassportModel,
    revision: TravellerDocumentRevisionModel, *, make_default: bool = False,
) -> None:
    current = await session.scalar(select(TravellerPassportModel).where(
        TravellerPassportModel.traveller_id == person.id, TravellerPassportModel.is_default.is_(True),
    ).with_for_update())
    choose = make_default or current is None or current.id == passport.id
    if not make_default and current is not None and current.id != passport.id:
        current_revision = await session.scalar(select(TravellerDocumentRevisionModel).where(
            TravellerDocumentRevisionModel.passport_id == current.id,
            TravellerDocumentRevisionModel.status == "accepted",
        ).order_by(TravellerDocumentRevisionModel.revision_number.desc()).limit(1))
        choose = (revision.issue_date is not None and current_revision is not None
                  and current_revision.issue_date is not None and revision.issue_date > current_revision.issue_date)
    if choose and current is not None and current.id != passport.id:
        current.is_default = False
        await session.flush()
    passport.status = "accepted"
    passport.is_default = choose
    passport.revision += 1
