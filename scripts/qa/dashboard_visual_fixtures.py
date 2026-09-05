"""Additional inert records for isolated dashboard rendering; no provider calls."""
from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

from app.core.config.settings import get_settings
from app.infrastructure.database.email_models import (
    EmailConnectionModel,
    EmailMessageModel,
)
from app.infrastructure.database.gc_mobile_models import (
    ClientOrganizationModel,
    GCGroupAccessModel,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession


async def seed_visual_records(
    session: AsyncSession,
    *,
    namespace: uuid.UUID,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    owner_id: uuid.UUID,
    passenger_ids: tuple[uuid.UUID, ...],
) -> None:
    settings = get_settings()
    if settings.app_env != "development" or not settings.database.db.startswith("passdetection_ci_"):
        raise RuntimeError("Visual fixtures require an isolated development QA database")
    connection_id = uuid.uuid5(namespace, "inert-email-connection")
    if await session.get(EmailConnectionModel, connection_id) is None:
        session.add(EmailConnectionModel(
            id=connection_id, agency_id=agency_id, owner_user_id=owner_id,
            provider="gmail", provider_account_id="isolated-visual-qa-no-provider",
            email_address="visual.qa@example.test", display_name="QA mailbox (paused)",
            status="paused", sync_state="idle", scopes=[], ai_processing_enabled=False,
        ))
        await session.flush()
    message_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    if await session.get(EmailMessageModel, message_id) is None:
        session.add(EmailMessageModel(
            id=message_id, agency_id=agency_id, owner_user_id=owner_id,
            connection_id=connection_id, provider_message_id="visual-fixture-001",
            sender_address="travel.desk@example.test", sender_name="QA Travel Desk",
            subject="Travel Review Group - travel document update",
            body_excerpt="Synthetic visual review record. No provider connection or customer information.",
            received_at=datetime.now(UTC), relevance_status="relevant",
            processing_status="completed", group_id=group_id,
        ))
    control_id = uuid.uuid5(namespace, "gc-group-control")
    organization_id = uuid.uuid5(namespace, "gc-client-organization")
    if await session.get(ClientOrganizationModel, organization_id) is None:
        session.add(ClientOrganizationModel(
            id=organization_id, agency_id=agency_id, name="QA Travel Company",
            normalized_name="qa travel company", status="active",
        ))
        await session.flush()
    control = await session.get(GCGroupAccessModel, control_id)
    if control is None:
        session.add(GCGroupAccessModel(
            id=control_id, agency_id=agency_id, group_id=group_id,
            client_organization_id=organization_id,
            is_enabled=False, passenger_access_enabled=False,
            client_manager_access_enabled=False, coordinator_access_enabled=False,
        ))
    else:
        control.client_organization_id = organization_id
    storage = MinioStorageRepository()
    await storage.ensure_bucket_exists()
    placeholder = Image.new("RGB", (900, 600), "#f1f5f9")
    drawing = ImageDraw.Draw(placeholder)
    drawing.rectangle((30, 30, 870, 570), outline="#94a3b8", width=3)
    drawing.text((80, 240), "SYNTHETIC QA DOCUMENT", fill="#334155", font_size=40)
    drawing.text((80, 310), "No passenger data. Layout inspection only.", fill="#475569", font_size=28)
    with io.BytesIO() as image_bytes:
        placeholder.save(image_bytes, format="JPEG")
        content = image_bytes.getvalue()
    placeholder.close()
    for passenger_id in passenger_ids:
        await storage.upload_file(content, f"enterprise-browser-qa/{passenger_id}.jpg", "image/jpeg")
    from dashboard_whatsapp_fixtures import seed_whatsapp_visual_records

    await seed_whatsapp_visual_records(
        session, namespace=namespace, agency_id=agency_id, group_id=group_id, owner_id=owner_id,
    )
