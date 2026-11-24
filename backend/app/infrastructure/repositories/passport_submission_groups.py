"""Group summary SQL and its explicit public projection."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import (
    CONFIRMED_PASSPORT_STATUS_VALUES,
    PENDING_REVIEW_PASSPORT_STATUS_VALUES,
    PassportProcessingStatus,
    User,
)
from app.domain.repositories.interfaces import PassportSubmissionGroupSummary
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.repositories.passport_submission_queries import (
    _apply_manager_group_scope,
    _office_visible_statuses,
)


async def list_group_summaries_by_agency(
    session: AsyncSession,
    agency_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 50,
    exclude_archived_groups: bool = True,
    created_by_user_id: uuid.UUID | None = None,
    visible_to_user: User | None = None,
) -> list[PassportSubmissionGroupSummary]:
    stmt = (
        select(
            ClientGroupModel.id.label("group_id"),
            ClientGroupModel.name.label("group_name"),
            ClientGroupModel.status.label("group_status"),
            ClientGroupModel.destination.label("destination"),
            ClientGroupModel.travel_date.label("travel_date"),
            ClientGroupModel.return_date.label("return_date"),
            ClientGroupModel.timezone.label("timezone"),
            ClientGroupModel.package_name.label("package_name"),
            ClientGroupModel.notes.label("notes"),
            ClientGroupModel.departure_cities.label("departure_cities"),
            ClientGroupModel.base_city_enabled.label("base_city_enabled"),
            ClientGroupModel.nearest_international_airport_enabled.label(
                "nearest_international_airport_enabled"
            ),
            ClientGroupModel.staff_code_enabled.label("staff_code_enabled"),
            ClientGroupModel.agent_employee_code_enabled.label("agent_employee_code_enabled"),
            ClientGroupModel.meal_preference_enabled.label("meal_preference_enabled"),
            ClientGroupModel.import_only.label("import_only"),
            ClientGroupModel.require_selfie.label("require_selfie"),
            ClientGroupModel.custom_questions.label("custom_questions"),
            ClientGroupModel.custom_details.label("custom_details"),
            ClientGroupModel.upload_configuration.label("upload_configuration"),
            ClientGroupModel.allow_files_from_device.label("allow_files_from_device"),
            ClientGroupModel.ask_nearest_domestic_airport.label("ask_nearest_domestic_airport"),
            ClientGroupModel.relation_with_qualifier_enabled.label(
                "relation_with_qualifier_enabled"
            ),
            ClientGroupModel.designation_enabled.label("designation_enabled"),
            ClientGroupModel.agency_dealership_name_enabled.label("agency_dealership_name_enabled"),
            func.count(PassportSubmissionModel.id).label("total_passports"),
            func.sum(
                case(
                    (
                        PassportSubmissionModel.status.in_(PENDING_REVIEW_PASSPORT_STATUS_VALUES),
                        1,
                    ),
                    else_=0,
                )
            ).label("pending_review_count"),
            func.sum(
                case(
                    (
                        PassportSubmissionModel.status.in_(CONFIRMED_PASSPORT_STATUS_VALUES),
                        1,
                    ),
                    else_=0,
                )
            ).label("confirmed_count"),
            func.sum(
                case(
                    (PassportSubmissionModel.status == PassportProcessingStatus.FAILED.value, 1),
                    else_=0,
                )
            ).label("failed_count"),
            func.coalesce(
                func.max(PassportSubmissionModel.updated_at), ClientGroupModel.created_at
            ).label("latest_submission_at"),
        )
        .outerjoin(
            PassportSubmissionModel,
            and_(
                PassportSubmissionModel.group_id == ClientGroupModel.id,
                PassportSubmissionModel.status.in_(_office_visible_statuses()),
            ),
        )
        .where(ClientGroupModel.agency_id == agency_id)
    )
    if exclude_archived_groups:
        stmt = stmt.where(ClientGroupModel.status.notin_(["archived", "deleted"]))
    if created_by_user_id:
        stmt = _apply_manager_group_scope(stmt, created_by_user_id)
    if visible_to_user:
        stmt = AuthorizationPolicy.apply_group_visibility_scope(stmt, visible_to_user)
    stmt = (
        stmt.group_by(
            ClientGroupModel.id,
            ClientGroupModel.name,
            ClientGroupModel.status,
            ClientGroupModel.destination,
            ClientGroupModel.travel_date,
            ClientGroupModel.return_date,
            ClientGroupModel.timezone,
            ClientGroupModel.package_name,
            ClientGroupModel.notes,
            ClientGroupModel.departure_cities,
            ClientGroupModel.base_city_enabled,
            ClientGroupModel.nearest_international_airport_enabled,
            ClientGroupModel.staff_code_enabled,
            ClientGroupModel.agent_employee_code_enabled,
            ClientGroupModel.meal_preference_enabled,
            ClientGroupModel.import_only,
            ClientGroupModel.require_selfie,
            ClientGroupModel.custom_questions,
            ClientGroupModel.custom_details,
            ClientGroupModel.upload_configuration,
            ClientGroupModel.allow_files_from_device,
            ClientGroupModel.ask_nearest_domestic_airport,
            ClientGroupModel.relation_with_qualifier_enabled,
            ClientGroupModel.designation_enabled,
            ClientGroupModel.agency_dealership_name_enabled,
            ClientGroupModel.created_at,
        )
        .order_by(
            func.coalesce(
                func.max(PassportSubmissionModel.updated_at), ClientGroupModel.created_at
            ).desc(),
            ClientGroupModel.id.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [
        PassportSubmissionGroupSummary(
            group_id=row.group_id,
            group_name=row.group_name,
            group_status=row.group_status,
            total_passports=int(row.total_passports),
            pending_review_count=int(row.pending_review_count or 0),
            confirmed_count=int(row.confirmed_count or 0),
            failed_count=int(row.failed_count or 0),
            latest_submission_at=row.latest_submission_at,
            destination=row.destination,
            travel_date=row.travel_date,
            return_date=row.return_date,
            timezone=row.timezone,
            package_name=row.package_name,
            departure_cities=list(row.departure_cities or []),
            base_city_enabled=row.base_city_enabled,
            nearest_international_airport_enabled=row.nearest_international_airport_enabled,
            staff_code_enabled=row.staff_code_enabled,
            agent_employee_code_enabled=row.agent_employee_code_enabled,
            meal_preference_enabled=row.meal_preference_enabled,
            import_only=row.import_only,
            require_selfie=row.require_selfie,
            custom_questions=list(row.custom_questions or []),
            custom_details=list(row.custom_details or []),
            upload_configuration=row.upload_configuration,
            allow_files_from_device=row.allow_files_from_device,
            ask_nearest_domestic_airport=row.ask_nearest_domestic_airport,
            relation_with_qualifier_enabled=(row.relation_with_qualifier_enabled),
            designation_enabled=row.designation_enabled,
            agency_dealership_name_enabled=(row.agency_dealership_name_enabled),
            notes=row.notes,
        )
        for row in result.all()
    ]
