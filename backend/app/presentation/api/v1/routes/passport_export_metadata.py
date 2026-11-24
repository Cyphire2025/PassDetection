"""Group metadata and immutable person snapshots for an authorized export."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.infrastructure.database.models import (
    ClientGroupModel,
)
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportPersonSnapshot,
)


def _export_people_snapshot(
    submissions: list[PassportSubmission],
) -> list[PassportExportPersonSnapshot]:
    people: list[PassportExportPersonSnapshot] = []
    for submission in submissions:
        fields = submission.confirmed_fields or submission.extracted_fields or {}
        passport_number = fields.get("passport_number")
        people.append(
            {
                "submission_id": str(submission.id),
                "client_name": submission.client_name,
                "client_phone": submission.client_phone,
                "client_email": submission.client_email,
                "passport_number": (str(passport_number).strip() if passport_number else None),
            }
        )
    return people


def _international_airport_is_enabled(
    group: ClientGroup | ClientGroupModel,
) -> bool:
    """Honor the current option and legacy groups that already stored choices."""

    return group.nearest_international_airport_enabled or bool(group.departure_cities)


def _group_export_details(
    group: ClientGroup | ClientGroupModel,
) -> dict[str, Any]:
    return {
        "name": group.name,
        "passport_ecr_enabled": bool(
            (getattr(group, "upload_configuration", None) or {}).get("passport_ecr_enabled", False)
        ),
        "destination": group.destination,
        "travel_date": group.travel_date.isoformat() if group.travel_date else None,
        "return_date": group.return_date.isoformat() if group.return_date else None,
        "package_name": group.package_name,
        "nearest_international_airport_enabled": (_international_airport_is_enabled(group)),
        "ask_nearest_domestic_airport": group.ask_nearest_domestic_airport,
        "base_city_enabled": group.base_city_enabled,
        "staff_code_enabled": group.staff_code_enabled,
        "agent_employee_code_enabled": group.agent_employee_code_enabled,
        "meal_preference_enabled": group.meal_preference_enabled,
        "relation_with_qualifier_enabled": (group.relation_with_qualifier_enabled),
        "designation_enabled": group.designation_enabled,
        "agency_dealership_name_enabled": (group.agency_dealership_name_enabled),
        "custom_questions": list(group.custom_questions or []),
        "custom_details": list(group.custom_details or []),
    }


async def _export_group_details(
    session: AsyncSession,
    group_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, Any]]:
    if not group_ids:
        return {}
    result = await session.execute(
        select(ClientGroupModel).where(ClientGroupModel.id.in_(set(group_ids)))
    )
    return {group.id: _group_export_details(group) for group in result.scalars().all()}
