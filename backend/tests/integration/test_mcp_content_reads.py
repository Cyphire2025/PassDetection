"""Retained GC/email reads preserve publication, receipt and personal ownership rules."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.application.mcp.content_reads import EMAIL_KINDS, GC_KINDS, MCPContentReadService
from app.application.mcp.credentials import MCPAuthError
from app.application.mobile.authored_notification_service import send_notification
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    GCCommonDocumentModel,
    GCGroupAccessModel,
    GCItineraryDayModel,
    GCItineraryItemModel,
    GCItineraryVersionModel,
    MobileNotificationModel,
    MobilePushDeliveryModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    UserModel,
)
from tests.authored_notification_fixtures import authored_audience, reviewed_draft


@pytest.fixture
async def content_reads(db_session):
    actor = UserModel(id=uuid.uuid4(), email="reader@example.test", hashed_password="SECRET_PASSWORD", full_name="Reader", role="super_admin")
    other = UserModel(id=uuid.uuid4(), email="other@example.test", hashed_password="SECRET_PASSWORD", full_name="Other", role="super_admin")
    agencies = [AgencyModel(id=uuid.uuid4(), name=f"Agency{i}", email=f"agency{i}@example.test") for i in range(2)]
    db_session.add_all([actor, other, *agencies])
    await db_session.flush()
    groups = [ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Trip", token=f"SECRET_TOKEN{i}") for i, agency in enumerate(agencies)]
    db_session.add_all(groups)
    await db_session.flush()
    return db_session, actor, other, agencies, groups, MCPContentReadService(db_session, cursor_secret="content-secret")


@pytest.mark.asyncio
async def test_unconfigured_gc_and_empty_owned_mailboxes_are_explicit(content_reads):
    _, actor, _, agencies, groups, service = content_reads
    for kind in GC_KINDS - {"itinerary_days", "itinerary_items"}:
        result = await service.gc_content(user_id=actor.id, agency_id=agencies[0].id, group_id=groups[0].id, kind=kind)
        assert result["items"] == [] and result["configured"] is False
        assert result["availability"]["app_availability_reason"] == "not_configured"
    for kind in EMAIL_KINDS:
        assert (await service.email(user_id=actor.id, kind=kind))["items"] == []
    with pytest.raises(ValueError, match="scope"):
        await service.gc_content(user_id=actor.id, agency_id=agencies[1].id, group_id=groups[0].id, kind="access")


@pytest.mark.asyncio
async def test_gc_versions_optional_content_and_shared_availability(content_reads):
    session, actor, _, agencies, groups, service = content_reads
    group = groups[0]
    access = GCGroupAccessModel(id=uuid.uuid4(), agency_id=group.agency_id, group_id=group.id,
        is_enabled=True, passenger_access_enabled=True, access_expires_at=datetime.now(UTC) - timedelta(days=1))
    session.add(access)
    await session.flush()
    common = dict(agency_id=group.agency_id, group_id=group.id, gc_group_access_id=access.id)
    versions = [GCItineraryVersionModel(id=uuid.uuid4(), **common, version=i+1, title="Itinerary", status=status,
        summary="UNTRUSTED " * 1000, content_checksum="a" * 64, published_at=datetime.now(UTC) if status == "published" else None) for i, status in enumerate(("draft", "published"))]
    announcements = [GCAnnouncementModel(id=uuid.uuid4(), **common, version=1, title="Notice", body="UNTRUSTED_BODY", status=status,
        published_at=datetime.now(UTC) if status == "retired" else None) for status in ("draft", "retired")]
    document = GCCommonDocumentModel(id=uuid.uuid4(), **common, version=1, category="other", title="Info", storage_key="SECRET_STORAGE",
        safe_filename="information.pdf", media_type="application/pdf", byte_size=10, checksum_sha256="a" * 64, status="published",
        published_at=datetime.now(UTC), passenger_visible=True)
    session.add_all([*versions, *announcements, document])
    await session.flush()
    day = GCItineraryDayModel(id=uuid.uuid4(), **common, itinerary_version_id=versions[0].id, day_number=1, title="Day")
    session.add(day)
    await session.flush()
    session.add(GCItineraryItemModel(id=uuid.uuid4(), **common, itinerary_version_id=versions[0].id,
        itinerary_day_id=day.id, title="Arrival", description="UNTRUSTED_DESCRIPTION", map_uri="SECRET_URL", contact_phone="SECRET_PHONE"))
    await session.flush()
    args = dict(user_id=actor.id, agency_id=agencies[0].id, group_id=group.id)
    result = await service.gc_content(**args, kind="itineraries")
    assert {row["status"] for row in result["items"]} == {"draft", "published"}
    assert result["availability"]["app_availability"] == "ended" and "UNTRUSTED" not in json.dumps(result)
    detailed = await service.gc_content(**args, kind="itineraries", version_id=versions[0].id, include_text=True)
    assert detailed["items"][0]["summary_truncated"] is True and len(detailed["items"][0]["summary"]) == 4000
    for kind in ("itinerary_days", "itinerary_items"):
        page = await service.gc_content(**args, kind=kind, version_id=versions[0].id)
        assert len(page["items"]) == 1 and "SECRET" not in json.dumps(page)
    docs = await service.gc_content(**args, kind="documents")
    assert docs["items"][0]["byte_size"] == 10 and "SECRET" not in json.dumps(docs)
    assert {row["status"] for row in (await service.gc_content(**args, kind="announcements"))["items"]} == {"draft", "retired"}
    with pytest.raises(ValueError, match="version"):
        await service.gc_content(**args, kind="itinerary_items", version_id=uuid.uuid4())
    assert (await session.scalar(select(AuditLogModel).where(AuditLogModel.action == "mcp.content.authorized_read"))).metadata_json["family"] == "gc_app"


@pytest.mark.asyncio
async def test_notification_history_reuses_recipient_and_device_projection_without_dispatch(db_session):
    principal, accesses, _, _, registration = await authored_audience(db_session)
    draft, _, request = await reviewed_draft(db_session, principal)
    await send_notification(db_session, agency_id=principal.agency_id, actor_id=principal.id, draft_id=draft.id, body=request)
    actor = await db_session.get(UserModel, principal.id)
    actor.role = "super_admin"
    notifications = list((await db_session.scalars(select(MobileNotificationModel))).all())
    notifications[0].status = "sent"
    notifications[1].status, notifications[1].failure_code = "failed", "provider_outcome_unknown"
    db_session.add(MobilePushDeliveryModel(id=uuid.uuid4(), agency_id=principal.agency_id, notification_id=notifications[0].id,
        registration_id=registration.id, provider="fcm", status="provider_accepted", provider_ticket_id="SECRET_PROVIDER_TICKET", submitted_at=datetime.now(UTC)))
    await db_session.flush()
    service = MCPContentReadService(db_session, cursor_secret="notification-test")
    result = await service.notifications(user_id=actor.id, agency_id=principal.agency_id, kind="batches")
    row = result["items"][0]
    assert row["recipient_counts"]["total"] == 2 and row["recipient_counts"]["sent"] == 1 and row["recipient_counts"]["unknown"] == 1
    assert row["device_delivery_counts"]["total"] == 1 and row["device_delivery_counts"]["provider_accepted"] == 1
    assert row["device_delivery_counts"]["delivered"] == 0 and "SECRET" not in json.dumps(result)
    assert "body" not in row and row["group_count"] == len(accesses)
    assert (await service.notifications(user_id=actor.id, agency_id=principal.agency_id, kind="drafts"))["items"][0]["status"] == "sent"
    assert notifications[1].status == "failed" and notifications[1].failure_code == "provider_outcome_unknown"


async def mailbox(session, owner, agency, *, count=1):
    connection = EmailConnectionModel(id=uuid.uuid4(), agency_id=agency.id, owner_user_id=owner.id, provider="gmail",
        provider_account_id=str(uuid.uuid4()), email_address=f"SECRET_{uuid.uuid4()}@example.test", access_token_ciphertext=b"SECRET_ACCESS",
        refresh_token_ciphertext=b"SECRET_REFRESH", sync_cursor="SECRET_CURSOR", status="active", last_error_message="SECRET_RAW_ERROR")
    session.add(connection)
    await session.flush()
    stamp = datetime.now(UTC) - timedelta(minutes=2)
    messages = [EmailMessageModel(id=uuid.uuid4(), agency_id=agency.id, owner_user_id=owner.id, connection_id=connection.id,
        provider_message_id=str(uuid.uuid4()), received_at=stamp, created_at=stamp, subject="UNTRUSTED_SUBJECT", body_excerpt="x" * 5000,
        sender_address="sender@example.test", evidence_json={"secret":"SECRET_EVIDENCE"}) for _ in range(count)]
    session.add_all(messages)
    await session.flush()
    return connection, messages


@pytest.mark.asyncio
async def test_personal_mailbox_boundary_and_credential_omission_for_superadmin(content_reads):
    session, actor, other, agencies, _, service = content_reads
    own, own_messages = await mailbox(session, actor, agencies[0])
    foreign, foreign_messages = await mailbox(session, other, agencies[0])
    other_agency, _ = await mailbox(session, actor, agencies[1])
    common = dict(agency_id=agencies[0].id, owner_user_id=actor.id, message_id=own_messages[0].id)
    artifact = EmailArtifactModel(id=uuid.uuid4(), **common, provider_artifact_id="SECRET_PROVIDER_ARTIFACT", kind="attachment",
        filename="ticket.pdf", storage_key="SECRET_STORAGE", source_url_ciphertext=b"SECRET_SOURCE_URL", source_url_encryption_key_version=1, error_message="SECRET_ERROR")
    session.add(artifact)
    await session.flush()
    session.add(EmailReviewItemModel(id=uuid.uuid4(), **common, artifact_id=artifact.id, review_type="possible_revision",
        proposed_action="review", proposed_payload={"secret":"SECRET_PAYLOAD"}, evidence={"secret":"SECRET_EVIDENCE"}))
    session.add(EmailActivityEventModel(id=uuid.uuid4(), **common, connection_id=own.id, event_key="SECRET_EVENT_KEY", event_type="discovered",
        stage="info", summary_code="SECRET_SUMMARY", details={"secret":"SECRET_DETAILS"}))
    await session.flush()
    connections = await service.email(user_id=actor.id, kind="connections")
    assert {row["id"] for row in connections["items"]} == {str(own.id), str(other_agency.id)}
    assert "SECRET" not in json.dumps(connections)
    for kind in EMAIL_KINDS:
        result = await service.email(user_id=actor.id, agency_id=agencies[0].id, connection_id=own.id, kind=kind)
        assert len(result["items"]) == 1 and "SECRET" not in json.dumps(result) and "UNTRUSTED" not in json.dumps(result)
    for arguments in ({"connection_id":foreign.id}, {"message_id":foreign_messages[0].id}, {"connection_id":own.id, "message_id":foreign_messages[0].id}):
        with pytest.raises(ValueError, match="personal mailbox"):
            await service.email(user_id=actor.id, kind="messages", **arguments)
    detail = await service.email(user_id=actor.id, kind="messages", message_id=own_messages[0].id, include_text=True)
    assert detail["items"][0]["subject"] == "UNTRUSTED_SUBJECT" and detail["items"][0]["body_excerpt_truncated"] is True
    assert len(detail["items"][0]["body_excerpt"]) == 4000 and "SECRET" not in json.dumps(detail)


@pytest.mark.asyncio
async def test_content_pages_cursor_binding_role_and_bounds(content_reads):
    session, actor, _, agencies, _, service = content_reads
    connection, _ = await mailbox(session, actor, agencies[0], count=103)
    args = dict(user_id=actor.id, connection_id=connection.id, kind="messages", page_size=12)
    first = page = await service.email(**args)
    seen = [row["id"] for row in page["items"]]
    while page["has_more"]:
        page = await service.email(**args, cursor=page["next_cursor"])
        seen += [row["id"] for row in page["items"]]
    assert len(seen) == len(set(seen)) == 103
    with pytest.raises(ValueError, match="cursor"):
        await service.email(**args, cursor=first["next_cursor"], include_text=True)
    with pytest.raises(ValueError, match="Page size"):
        await service.notifications(user_id=actor.id, agency_id=agencies[0].id, kind="batches", page_size=101)
    actor.role = "agency_admin"
    await session.flush()
    with pytest.raises(MCPAuthError):
        await service.email(**args)
