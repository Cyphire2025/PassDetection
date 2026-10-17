"""Load branding for an already authorized page of groups in one bounded query."""

import uuid
from collections.abc import Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.storage.branding_urls import branding_image_url


def company_branding_metadata(company: ClientOrganizationModel | None) -> dict[str, str | None]:
    if company is None:
        return {"company_name": None, "company_logo_url": None}
    return {"company_name": company.name, "company_logo_url": company.logo_url}


async def group_branding_metadata(session: AsyncSession, group_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[str, str | None]]:
    if not group_ids:
        return {}
    rows = (await session.execute(select(
        ClientGroupModel.id, ClientGroupModel.agency_id, ClientGroupModel.banner_image_key,
        ClientOrganizationModel.id.label("company_id"), ClientOrganizationModel.name,
        ClientOrganizationModel.logo_image_key,
    ).outerjoin(ClientOrganizationModel, and_(
        ClientOrganizationModel.id == ClientGroupModel.company_id,
        ClientOrganizationModel.agency_id == ClientGroupModel.agency_id,
        ClientOrganizationModel.status != "deleted",
    )).where(ClientGroupModel.id.in_(group_ids)))).mappings()
    return {row["id"]: {
        "company_name": row["name"],
        "company_logo_url": branding_image_url("company-logo", row["company_id"], row["agency_id"], row["logo_image_key"]),
        "banner_url": branding_image_url("group-banner", row["id"], row["agency_id"], row["banner_image_key"]),
    } for row in rows}
