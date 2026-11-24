"""Private image readers select scoped keys and retain view/editor boundaries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.domain.value_objects.passport_image_crop import PassportImageCrop, PassportImageType
from app.domain.value_objects.passport_visa_ai_image import PassportVisaAiImage
from app.presentation.api.v1.routes.passport_routes import images, visa_ai_library
from tests.route_dependencies import set_route_dependency


@pytest.fixture
def image_reader(monkeypatch):
    submission = SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4(), agency_id=uuid.uuid4())
    source = f"photo/{submission.id}.jpg"
    authorize = AsyncMock(return_value=(submission, source))
    crop = SimpleNamespace(get=AsyncMock(return_value=None))
    storage = SimpleNamespace(get_file=AsyncMock(return_value=b"synthetic private image"))
    factory = MagicMock(return_value=storage)
    stream = StreamingResponse(iter([b"synthetic stream"]))
    private_stream = AsyncMock(return_value=stream)
    for owner in [images, visa_ai_library]:
        for name, value in [
            ("_authorized_staff_passport_image", authorize),
            ("PassportImageCropRepository", lambda _session: crop),
            ("MinioStorageRepository", factory),
            ("private_object_streaming_response", private_stream),
        ]:
            set_route_dependency(monkeypatch, owner, name, value)
    return SimpleNamespace(
        submission=submission,
        source=source,
        authorize=authorize,
        crop=crop,
        storage=storage,
        factory=factory,
        private_stream=private_stream,
        stream=stream,
        actor=SimpleNamespace(),
        session=MagicMock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "denied", "active_crop"),
    [
        (kind, denied, False)
        for kind in ["edit-source", "view", "original", "metadata"]
        for denied in [False, True]
    ]
    + [(kind, False, True) for kind in ["edit-source", "view", "metadata"]],
)
async def test_scoped_image_reader(image_reader, kind, denied, active_crop):
    ctx = image_reader
    image_type = PassportImageType.VISA_PHOTO
    if denied:
        ctx.authorize.side_effect = HTTPException(403, "Synthetic denied image scope")
    if active_crop:
        ctx.crop.get.return_value = PassportImageCrop(
            submission_id=ctx.submission.id,
            image_type=image_type,
            source_storage_key=ctx.source,
            derived_storage_key="passport-crops/current.jpg",
            edit_source_storage_key="passport-edits/current.jpg",
            active=True,
            x=0,
            y=0,
            width=1,
            height=1,
            rotation_degrees=0,
            source_width=900,
            source_height=600,
            revision=2,
        )
    args = dict(
        submission_id=ctx.submission.id,
        image_type=image_type,
        current_user=ctx.actor,
        session=ctx.session,
    )
    handlers = {
        "edit-source": images.get_passport_image_edit_source,
        "view": images.get_passport_image_view,
        "original": images.get_passport_image_original,
        "metadata": images.get_passport_image_crop,
    }
    if kind in {"edit-source", "view"}:
        args["crop_revision"] = None
    if kind in {"edit-source", "original"}:
        args["range_header"] = "bytes=0-10"
    if denied:
        with pytest.raises(HTTPException) as caught:
            await handlers[kind](**args)
        assert caught.value.status_code == 403
        ctx.crop.get.assert_not_awaited()
        ctx.factory.assert_not_called()
    else:
        response = await handlers[kind](**args)
        if kind in {"edit-source", "original"}:
            assert response is ctx.stream
            call = ctx.private_stream.await_args.kwargs
            expected = (
                "passport-edits/current.jpg"
                if kind == "edit-source" and active_crop
                else ctx.source
            )
            assert call["key"] == expected
            assert call["storage"] is ctx.storage
            assert call["range_header"] == "bytes=0-10"
            assert call["media_type"] == "image/jpeg"
        elif kind == "view":
            assert response.headers["Cache-Control"] == "private, no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert (
                b"".join([chunk async for chunk in response.body_iterator])
                == b"synthetic private image"
            )
            expected = "passport-crops/current.jpg" if active_crop else ctx.source
            ctx.storage.get_file.assert_awaited_once_with(expected)
        else:
            assert response.revision == (2 if active_crop else 0)
            assert response.ai_edited == active_crop
        if kind == "original":
            ctx.crop.get.assert_not_awaited()
        else:
            ctx.crop.get.assert_awaited_once_with(ctx.submission.id, image_type)
    ctx.authorize.assert_awaited_once_with(
        submission_id=ctx.submission.id,
        image_type=image_type,
        current_user=ctx.actor,
        session=ctx.session,
        require_editor=kind != "view",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "outcome"),
    [
        ("list", "success"),
        ("list", "forbidden"),
        ("image", "success"),
        ("image", "missing"),
        ("image", "forbidden"),
    ],
)
async def test_scoped_saved_ai_reader(monkeypatch, image_reader, kind, outcome):
    ctx = image_reader
    generation = PassportVisaAiImage(
        id=uuid.uuid4(),
        submission_id=ctx.submission.id,
        original_source_storage_key=ctx.source,
        input_storage_key=ctx.source,
        generated_storage_key="passport-ai-library/synthetic.jpg",
        prompt="Keep original",
        prompt_sha256="b" * 64,
        content_sha256="a" * 64,
        model="synthetic",
        created_by_user_id=None,
        created_at=datetime.now(UTC),
    )
    repository = SimpleNamespace(
        list_for_submission=AsyncMock(return_value=[generation]),
        get_for_submission=AsyncMock(return_value=None if outcome == "missing" else generation),
    )
    factory = MagicMock(return_value=repository)
    set_route_dependency(monkeypatch, visa_ai_library, "PassportVisaAiImageRepository", factory)
    if outcome == "forbidden":
        ctx.authorize.side_effect = HTTPException(403, "Synthetic denied image scope")
    args = dict(submission_id=ctx.submission.id, current_user=ctx.actor, session=ctx.session)
    handler = (
        visa_ai_library.list_visa_ai_image_library
        if kind == "list"
        else visa_ai_library.get_visa_ai_library_image
    )
    if kind == "image":
        args.update(generation_id=generation.id, range_header=None)
    if outcome in {"forbidden", "missing"}:
        with pytest.raises(HTTPException) as caught:
            await handler(**args)
        assert caught.value.status_code == (403 if outcome == "forbidden" else 404)
        ctx.private_stream.assert_not_awaited()
        ctx.factory.assert_not_called()
    else:
        response = await handler(**args)
        if kind == "list":
            assert [item.id for item in response.items] == [generation.id]
            repository.list_for_submission.assert_awaited_once_with(ctx.submission.id)
        else:
            assert response is ctx.stream
            call = ctx.private_stream.await_args.kwargs
            assert call["key"] == generation.generated_storage_key
            assert call["storage"] is ctx.storage and call["range_header"] is None
    if outcome == "forbidden":
        factory.assert_not_called()
    elif kind == "image":
        repository.get_for_submission.assert_awaited_once_with(ctx.submission.id, generation.id)
    ctx.authorize.assert_awaited_once_with(
        submission_id=ctx.submission.id,
        image_type=PassportImageType.VISA_PHOTO,
        current_user=ctx.actor,
        session=ctx.session,
        require_editor=True,
    )
