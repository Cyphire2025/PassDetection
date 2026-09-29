"""Real canonical ZIP bytes, current crops, web parity and protected delivery."""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.image_exports import (
    ImageExportRequest,
    MCPImageExportService,
    image_export_operation,
)
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.models import (
    PassportExportHistoryModel,
    PassportImageCropModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.document_distribution_match_source import (
    _read_linked_document_match_source,
)
from app.presentation.api.v1.routes.passport_routes import image_exports as web
from tests.integration.test_mcp_artifacts import Storage
from tests.integration.test_mcp_artifacts import artifacts as artifacts


def png(color="red"):
    output = io.BytesIO()
    with Image.new("RGB", (64, 64), color) as image:
        image.save(output, format="PNG")
    return output.getvalue()


class Images(Storage):
    async def get_file(self, key):
        from app.domain.exceptions.exceptions import StorageError

        try:
            return self.objects[key][0]
        except KeyError as exc:
            raise StorageError("Synthetic missing image") from exc

    async def stat_file(self, key):
        from app.domain.exceptions.exceptions import StorageError

        try:
            return await super().stat_file(key)
        except KeyError as exc:
            raise StorageError("Synthetic missing image") from exc

    def retain(self, key, color):
        data = png(color)
        self.objects[key] = data, hashlib.sha256(data).hexdigest(), "image/png"


async def seed(f):
    f.images = Images()
    f.group.staff_code_enabled = True
    f.person = await add_person(f, "1")
    await f.session.commit()
    return f


async def add_person(f, suffix):
    row = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=f.agency.id,
        group_id=f.group.id,
        client_name=f"Synthetic Person {suffix}",
        status="staff_approved",
        image_s3_key=f"original/front-{suffix}.png",
        passport_back_s3_key=f"original/back-{suffix}.png",
        confirmed_fields={
            "given_name": "Synthetic",
            "surname": f"Person{suffix}",
            "passport_number": f"TEST{suffix}",
        },
        staff_metadata={"staff_code": suffix, "zone_name": "West"},
    )
    f.images.retain(row.image_s3_key, "red")
    f.images.retain(row.passport_back_s3_key, "blue")
    f.session.add(row)
    await f.session.flush()
    return row


def service(f):
    return MCPImageExportService(
        f.session,
        f.settings,
        web.image_export_support(),
        linked_source=_read_linked_document_match_source,
        artifacts=f.service,
        image_storage=f.images,
    )


async def queue(f, request=None, key=None):
    await f.session.refresh(f.agency)
    await f.session.refresh(f.group)
    request = request or ImageExportRequest(agency_id=f.agency.id, group_id=f.group.id)
    observed = await service(f).inspect(f.principal, request)
    definition = image_export_operation(
        f.settings, web.image_export_support(), linked_source=_read_linked_document_match_source
    )
    payload = {
        "export": request.model_dump(mode="json"),
        "expected_revision": observed["expected_revision"],
    }
    key = key or uuid.uuid4().hex
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


async def delivered(f, result):
    artifact = result["artifact"]
    response = await f.client.get(artifact["content_path"])
    assert response.status_code == 200, response.text
    ack = await f.client.post(
        f"/mcp/artifacts/{artifact['artifact_id']}/delivery",
        json={"byte_size": artifact["byte_size"], "sha256": artifact["sha256"]},
    )
    assert ack.status_code == 200, ack.text
    return response.content


async def test_current_crop_and_zone_names_match_web_zip_and_only_ack_completes_history(
    artifacts, monkeypatch
):
    f = await seed(artifacts)
    f.images.retain("crop/current.jpg", "green")
    f.session.add(
        PassportImageCropModel(
            submission_id=f.person.id,
            image_type="passport_front",
            source_storage_key=f.person.image_s3_key,
            derived_storage_key="crop/current.jpg",
            active=True,
            crop_x=0,
            crop_y=0,
            crop_width=1,
            crop_height=1,
            rotation_degrees=0,
            sharpness=1,
            source_width=64,
            source_height=64,
            revision=1,
            updated_by_user_id=f.user.id,
        )
    )
    await f.session.commit()
    originals = dict(f.images.objects)
    receipt, _, _ = await queue(f)
    result = await generate(f, receipt)
    history = await f.session.scalar(select(PassportExportHistoryModel))
    assert history.status == "prepared" and history.export_kind == "passport_images"
    monkeypatch.setattr(web, "MinioStorageRepository", lambda: f.images)
    actor = await UserRepository(f.session).get_by_id(f.user.id)
    response = await web.export_passport_images_by_group(
        f.group.id,
        export_mode="all",
        baseline_export_id=None,
        request_id=uuid.uuid4(),
        current_user=replace(actor, agency_id=f.agency.id),
        session=f.session,
    )
    expected = b"".join([part async for part in response.body_iterator])
    data = await delivered(f, result)
    assert data == expected
    archive = zipfile.ZipFile(io.BytesIO(data))
    images = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    assert len(images) == 2 and all("/West/" in name for name in images)
    assert any(content == png("green") for content in images.values())
    assert f.images.objects == originals
    await f.session.refresh(history)
    assert history.status == "completed"


async def test_incremental_uses_completed_image_baseline_and_selected_has_no_history(artifacts):
    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    await delivered(f, await generate(f, receipt))
    history = await f.session.scalar(select(PassportExportHistoryModel))
    second = await add_person(f, "2")
    await f.session.commit()
    request = ImageExportRequest(
        agency_id=f.agency.id,
        group_id=f.group.id,
        mode="incremental",
        baseline_export_id=history.id,
    )
    next_receipt, _, _ = await queue(f, request)
    next_result = await generate(f, next_receipt)
    archive = zipfile.ZipFile(io.BytesIO(await delivered(f, next_result)))
    assert all("Person 1" not in name for name in archive.namelist())
    assert any("Person 2" in name for name in archive.namelist())
    request = ImageExportRequest(
        agency_id=f.agency.id,
        group_id=f.group.id,
        selection="selected_passports",
        submission_ids=[second.id],
    )
    selected, _, _ = await queue(f, request)
    await delivered(f, await generate(f, selected))
    assert await f.session.scalar(select(func.count()).select_from(PassportExportHistoryModel)) == 2


async def test_retry_new_grant_and_expiry_do_not_regenerate_originals_or_history(artifacts):
    f = await seed(artifacts)
    receipt, key, payload = await queue(f)
    first = await generate(f, receipt)
    definition = image_export_operation(
        f.settings, web.image_export_support(), linked_source=_read_linked_document_match_source
    )
    replay = await MCPOperationService(f.session, f.settings, [definition]).execute(
        access_token=f.token,
        operation_name=definition.policy.name,
        idempotency_key=key,
        payload=payload,
    )
    await f.session.commit()
    assert replay == receipt
    assert (await generate(f, receipt))["artifact"] == first["artifact"]
    token, principal = await f.connect(["mcp:export"])
    new = await generate(f, receipt, token)
    assert new["artifact"]["artifact_id"] != first["artifact"]["artifact_id"]
    assert new["artifact"]["sha256"] == first["artifact"]["sha256"]
    row = await f.service.get(principal, new["artifact"]["artifact_id"])
    row.created_at = datetime.now(UTC) - timedelta(hours=2)
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await f.session.commit()
    with pytest.raises(ArtifactError, match="expired"):
        await generate(f, receipt, token)
    await f.session.rollback()
    assert len(f.storage.objects) == 1
    assert await f.session.scalar(select(func.count()).select_from(PassportExportHistoryModel)) == 1


async def test_crop_change_rejects_old_revision_and_failed_storage_leaves_queued(artifacts):
    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    f.person.passport_back_s3_key = "original/new-back.png"
    f.images.retain("original/new-back.png", "black")
    await f.session.commit()
    with pytest.raises(MCPOperationError, match="export_revision_changed"):
        await generate(f, receipt)
    await f.session.rollback()
    assert not f.storage.objects
    new_receipt, _, _ = await queue(f)
    f.images.corrupt = True
    from app.domain.exceptions.exceptions import StorageError

    with pytest.raises(StorageError):
        await generate(f, new_receipt)
    await f.session.rollback()
    assert not f.storage.objects
    assert await f.session.scalar(select(func.count()).select_from(PassportExportHistoryModel)) == 0
    f.images.corrupt = False
    assert (await generate(f, new_receipt))["status"] == "succeeded"


async def test_database_only_prepare_never_constructs_storage_or_zip(artifacts, monkeypatch):
    from app.application.mcp import image_exports

    f = await seed(artifacts)

    def forbidden():
        raise AssertionError("DB-only callback must not instantiate storage or render")

    monkeypatch.setattr(image_exports, "MinioStorageRepository", forbidden)
    monkeypatch.setattr(image_exports, "PassportImageZipExporter", forbidden)
    receipt, _, _ = await queue(f)
    assert receipt["status"] == "queued" and not f.storage.objects
    assert not f.images.read_sizes


async def test_missing_cached_crop_renders_saved_crop_and_preserves_source(artifacts):
    f = await seed(artifacts)
    f.session.add(
        PassportImageCropModel(
            submission_id=f.person.id,
            image_type="passport_front",
            source_storage_key=f.person.image_s3_key,
            derived_storage_key="missing/cache.jpg",
            active=True,
            crop_x=0,
            crop_y=0,
            crop_width=0.5,
            crop_height=0.5,
            rotation_degrees=0,
            sharpness=1,
            source_width=64,
            source_height=64,
            revision=1,
            updated_by_user_id=f.user.id,
        )
    )
    await f.session.commit()
    original = dict(f.images.objects)
    receipt, _, _ = await queue(f)
    archive = zipfile.ZipFile(io.BytesIO(await delivered(f, await generate(f, receipt))))
    front = next(name for name in archive.namelist() if name.endswith("_passportfront.jpg"))
    with Image.open(io.BytesIO(archive.read(front))) as rendered:
        assert rendered.size == (32, 32)
    assert f.images.objects == original


async def test_cancelled_generation_drains_and_closes_spool_then_releases_capacity(
    artifacts, monkeypatch
):
    from app.infrastructure.export import passport_image_zip_exporter

    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    entered, release = asyncio.Event(), asyncio.Event()
    original_stream = f.images.stream_file

    async def slow_stream(*args, **kwargs):
        entered.set()
        await release.wait()
        async for part in original_stream(*args, **kwargs):
            yield part

    f.images.stream_file = slow_stream
    spools = []
    original_spool = passport_image_zip_exporter.tempfile.SpooledTemporaryFile

    def spool(*args, **kwargs):
        target = original_spool(*args, **kwargs)
        spools.append(target)
        return target

    monkeypatch.setattr(passport_image_zip_exporter.tempfile, "SpooledTemporaryFile", spool)
    task = asyncio.create_task(generate(f, receipt))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    await f.session.rollback()
    assert spools and all(target.closed for target in spools)
    assert not f.storage.objects
    assert await f.session.scalar(select(func.count()).select_from(PassportExportHistoryModel)) == 0
    assert (await generate(f, receipt))["status"] == "succeeded"


async def test_exact_selection_rejects_missing_ids_and_required_source_pages(artifacts):
    from app.application.use_cases.passports.prepare_image_export import ImagePreparationError
    from app.infrastructure.export.passport_image_zip_exporter import MissingPassportImagesError

    f = await seed(artifacts)
    with pytest.raises(ImagePreparationError):
        await queue(
            f,
            ImageExportRequest(
                agency_id=f.agency.id,
                group_id=f.group.id,
                selection="selected_passports",
                submission_ids=[f.person.id, uuid.uuid4()],
            ),
        )
    await f.session.rollback()
    await f.session.refresh(f.person)
    f.person.passport_back_s3_key = None
    await f.session.commit()
    receipt, _, _ = await queue(f)
    with pytest.raises(MissingPassportImagesError):
        await generate(f, receipt)
    assert not f.storage.objects
