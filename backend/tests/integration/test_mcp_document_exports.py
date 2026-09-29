"""Canonical document-review XLSX, retained delivery semantics and no business writes."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.application.mcp import document_export_source, document_exports
from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.document_exports import (
    DocumentExportRequest,
    MCPDocumentExportService,
    document_export_operation,
)
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.application.use_cases.passports.prepare_group_excel import _canonical
from app.core.mcp_export_admission import export_slot
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
    PassportExportHistoryModel,
    PassportSubmissionModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import document_distribution_groups_read as web
from app.presentation.api.v1.routes import document_distribution_responses as responses
from app.presentation.mcp.document_export_tools import document_excel_support
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_exports import downloaded, person, values


async def seed(f):
    passengers = [person(f, index) for index in range(1, 4)]
    batch = DocumentDistributionBatchModel(
        id=uuid.uuid4(),
        agency_id=f.agency.id,
        group_id=f.group.id,
        document_type="visa",
        status="draft",
        uploaded_count=3,
        matched_count=2,
    )
    f.session.add_all([batch, *passengers])
    await f.session.flush()
    documents = [
        DistributedDocumentModel(
            id=uuid.uuid4(),
            batch_id=batch.id,
            agency_id=f.agency.id,
            group_id=f.group.id,
            passenger_id=passengers[0 if index < 2 else 1].id,
            document_type="visa",
            original_filename=f"Original-{index}.pdf",
            storage_key=f"original/never-read-{index}",
            detected_type="visa",
            match_status="matched" if index < 2 else "needs_review",
            match_confidence=0.97,
            match_reason="Existing review evidence",
        )
        for index in range(3)
    ]
    f.session.add_all(documents)
    await f.session.flush()
    now = datetime.now(UTC)
    deliveries = [
        DocumentWhatsAppDeliveryModel(
            id=uuid.uuid4(),
            agency_id=f.agency.id,
            group_id=f.group.id,
            document_batch_id=batch.id,
            distributed_document_id=documents[index // 2].id,
            passenger_id=passengers[0].id,
            send_batch_id=uuid.uuid4(),
            document_type="visa",
            document_filename=documents[index // 2].original_filename,
            passenger_name=passengers[0].client_name,
            phone_number="+919999990001",
            normalized_phone_number="919999990001",
            template_name="fixture",
            status="delivered" if index == 0 else "failed",
            created_at=now + timedelta(seconds=index),
            status_updated_at=now + timedelta(seconds=index),
            provider_message_id=f"private-provider-{uuid.uuid4()}",
            error_message="private-error",
        )
        for index in range(3)
    ]
    f.session.add_all(deliveries)
    await f.session.commit()
    f.passengers, f.batch, f.documents, f.deliveries = passengers, batch, documents, deliveries
    return f


def service(f):
    return MCPDocumentExportService(
        f.session, f.settings, document_excel_support(), artifacts=f.service
    )


async def queue(f, request=None, key=None):
    request = request or DocumentExportRequest(
        agency_id=f.agency.id, group_id=f.group.id, document_type="visa"
    )
    observed = await service(f).inspect(f.principal, request)
    definition = document_export_operation(f.settings, document_excel_support())
    key = key or uuid.uuid4().hex
    payload = {
        "export": request.model_dump(mode="json"),
        "expected_revision": observed["expected_revision"],
    }
    receipt = await MCPOperationService(f.session, f.settings, [definition]).execute(
        access_token=f.token,
        operation_name=definition.policy.name,
        idempotency_key=key,
        payload=payload,
    )
    await f.session.commit()
    return receipt, key, payload


async def generate(f, receipt, token=None):
    result = await service(f).generate(
        access_token=token or f.token, operation_id=uuid.UUID(receipt["operation_id"])
    )
    await f.session.commit()
    return result


async def business_snapshot(f):
    result = {}
    for model in (
        PassportSubmissionModel,
        DocumentDistributionBatchModel,
        DistributedDocumentModel,
        DocumentWhatsAppDeliveryModel,
        WhatsAppMessageLogModel,
        PassportExportHistoryModel,
    ):
        rows = (
            await f.session.scalars(
                select(model).order_by(model.id).execution_options(populate_existing=True)
            )
        ).all()
        result[model.__tablename__] = _canonical(
            [
                {column.key: getattr(row, column.key) for column in model.__table__.columns}
                for row in rows
            ]
        )
    return result


@pytest.mark.parametrize(
    "review_filter", ["all", "assigned", "missing", "sent", "not_sent", "multiple_pdfs"]
)
async def test_all_review_filters_match_website_without_presigning_or_business_changes(
    artifacts, monkeypatch, review_filter
):
    f = await seed(artifacts)
    calls = []

    class URLs:
        async def get_presigned_url(self, key):
            calls.append(key)
            return "https://fixture.invalid/never-fetched"

    monkeypatch.setattr(responses, "MinioStorageRepository", URLs)
    before = await business_snapshot(f)
    request = DocumentExportRequest(
        agency_id=f.agency.id,
        group_id=f.group.id,
        document_type="visa",
        review_filter=review_filter,
    )
    receipt, _, _ = await queue(f, request)
    result = await generate(f, receipt)
    assert not calls
    received = await downloaded(f, result)
    actor = await UserRepository(f.session).get_by_id(f.user.id)
    response = await web.export_document_assignments(
        f.group.id,
        "visa",
        review_filter=review_filter,
        search="",
        current_user=actor,
        session=f.session,
    )
    expected = b"".join([part async for part in response.body_iterator])
    assert values(received) == values(expected)
    assert len(calls) == 3
    rendered = str(values(received))
    assert "private-provider" not in rendered and "private-error" not in rendered
    assert "https://" not in rendered and "original/never-read" not in rendered
    assert result["artifact"]["purpose"] == "document_assignments_excel"
    assert await business_snapshot(f) == before


async def test_search_and_canonical_accepted_delivery_survive_later_failed_attempt(artifacts):
    f = await seed(artifacts)
    request = DocumentExportRequest(
        agency_id=f.agency.id,
        group_id=f.group.id,
        document_type="visa",
        search=" PERSON 1 ",
        review_filter="sent",
    )
    receipt, _, _ = await queue(f, request)
    content = str(values(await downloaded(f, await generate(f, receipt))))
    assert "Synthetic Person 1" in content and "Synthetic Person 2" not in content
    assert "sent" in content and "+919999990001" in content


async def test_retry_and_new_grant_recover_one_file_without_history(artifacts):
    f = await seed(artifacts)
    receipt, key, payload = await queue(f)
    first = await generate(f, receipt)
    definition = document_export_operation(f.settings, document_excel_support())
    replay = await MCPOperationService(f.session, f.settings, [definition]).execute(
        access_token=f.token,
        operation_name=definition.policy.name,
        idempotency_key=key,
        payload=payload,
    )
    await f.session.commit()
    assert replay == receipt
    assert (await generate(f, receipt))["artifact"] == first["artifact"]
    token, _principal = await f.connect()
    recovered = await generate(f, receipt, token)
    assert recovered["artifact"]["artifact_id"] != first["artifact"]["artifact_id"]
    assert recovered["artifact"]["sha256"] == first["artifact"]["sha256"]
    assert len(f.storage.objects) == 1
    assert await f.session.scalar(select(func.count()).select_from(PassportExportHistoryModel)) == 0


@pytest.mark.parametrize("change", ["name", "document", "delivery", "phone", "group"])
async def test_changed_review_source_rejects_saved_intent(artifacts, change):
    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    if change == "name":
        f.passengers[0].client_name = "Changed passenger"
    elif change == "document":
        f.documents[0].original_filename = "Changed filename.pdf"
    elif change == "delivery":
        f.deliveries[0].status = "failed"
    elif change == "phone":
        f.deliveries[0].phone_number = "+919999990009"
    else:
        f.group.name = "Changed group"
    await f.session.commit()
    with pytest.raises(MCPOperationError, match="export_revision_changed"):
        await generate(f, receipt)
    assert not f.storage.objects


@pytest.mark.parametrize(
    "bound", ["MAX_DOCUMENT_PASSENGERS", "MAX_DOCUMENT_ASSIGNMENTS", "MAX_DOCUMENT_DELIVERIES"]
)
async def test_every_source_limit_rejects_whole_scope(artifacts, monkeypatch, bound):
    f = await seed(artifacts)
    monkeypatch.setattr(document_export_source, bound, 2)
    with pytest.raises(ArtifactError, match="limit") as error:
        await queue(f)
    assert error.value.status_code == 413 and not f.storage.objects


async def test_snapshot_and_output_limits_do_not_retain_artifact(artifacts, monkeypatch):
    f = await seed(artifacts)
    with monkeypatch.context() as scoped:
        scoped.setattr(document_exports, "MAX_SNAPSHOT_BYTES", 10)
        with pytest.raises(ArtifactError, match="snapshot"):
            await queue(f)
    receipt, _, _ = await queue(f)
    monkeypatch.setattr(document_exports, "MAX_WORKBOOK_BYTES", 1000)
    with pytest.raises(ArtifactError, match="output limit"):
        await generate(f, receipt)
    await f.session.rollback()
    assert not f.storage.objects
    assert await f.session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 0


async def test_storage_rollback_and_expired_completed_file_never_regenerate(artifacts, monkeypatch):
    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    with monkeypatch.context() as scoped:

        async def unavailable(*args, **kwargs):
            raise OSError("fixture provider unavailable")

        scoped.setattr(f.storage, "put_transfer", unavailable)
        with pytest.raises(OSError):
            await generate(f, receipt)
        await f.session.rollback()
    first = await generate(f, receipt)
    row = await f.service.get(f.principal, first["artifact"]["artifact_id"])
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    row.created_at = datetime.now(UTC) - timedelta(hours=2)
    await f.session.commit()
    with pytest.raises(ArtifactError):
        await generate(f, receipt)
    assert len(f.storage.objects) == 1


async def test_exact_scope_and_input_shape_and_shared_admission(artifacts):
    f = await seed(artifacts)
    request = DocumentExportRequest(
        agency_id=uuid.uuid4(), group_id=f.group.id, document_type="visa"
    )
    with pytest.raises(ArtifactError, match="not found"):
        await service(f).inspect(f.principal, request)
    with pytest.raises(ValidationError):
        DocumentExportRequest(agency_id=f.agency.id, group_id=f.group.id, document_type="all")
    with export_slot():
        with pytest.raises(ArtifactError, match="capacity is busy"):
            await asyncio.create_task(service(f).inspect(f.principal, request))


async def test_same_physical_pdf_is_counted_once_and_foreign_assignment_is_rejected(artifacts):
    f = await seed(artifacts)
    f.documents[1].storage_key = f.documents[0].storage_key
    await f.session.commit()
    request = DocumentExportRequest(
        agency_id=f.agency.id,
        group_id=f.group.id,
        document_type="visa",
        review_filter="multiple_pdfs",
    )
    observed = await service(f).inspect(f.principal, request)
    assert observed["exported_count"] == 0
    from app.infrastructure.database.models import ClientGroupModel

    other = ClientGroupModel(
        id=uuid.uuid4(), agency_id=f.agency.id, name="Other", token=uuid.uuid4().hex
    )
    f.session.add(other)
    await f.session.flush()
    foreign = person(f, 99, group=other)
    f.session.add(foreign)
    await f.session.flush()
    f.documents[0].passenger_id = foreign.id
    await f.session.commit()
    with pytest.raises(ArtifactError, match="outside the current group"):
        await service(f).inspect(f.principal, request)


async def test_delivery_fence_after_storage_prevents_accessible_stale_artifact(
    artifacts, monkeypatch
):
    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    put = f.storage.put_transfer

    async def changed(*args, **kwargs):
        await put(*args, **kwargs)
        f.deliveries[0].phone_number = "+919999990099"
        await f.session.flush()

    monkeypatch.setattr(f.storage, "put_transfer", changed)
    with pytest.raises(MCPOperationError, match="export_revision_changed"):
        await generate(f, receipt)
    await f.session.rollback()
    assert await f.session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 0
    assert len(f.storage.objects) == 1  # Private orphan is covered by transfer TTL only.


async def test_joined_cell_limit_rejects_instead_of_truncating_filenames(artifacts, monkeypatch):
    from app.application.mcp import document_export_workbook

    f = await seed(artifacts)
    monkeypatch.setattr(document_export_workbook, "MAX_CELL_CHARACTERS", 20)
    with pytest.raises(ArtifactError, match="cell text limit"):
        await queue(f)
    assert not f.storage.objects
