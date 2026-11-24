"""A successful replacement preserves original evidence and removes only derivatives."""

from sqlalchemy import select, update

from app.infrastructure.database.models import PassportImageCropModel, PassportSubmissionModel
from app.infrastructure.database.passport_image_library_model import PassportImageLibraryItemModel
from tests.unit.presentation.document_import_authority_fixture import (
    perform_held_import,
    prepare_authority_import,
)


async def test_original_library_hold_and_both_crop_derivatives_survive_the_new_phase_boundary(
    db_session,
    monkeypatch,
    test_settings,
):
    context = await prepare_authority_import(
        db_session,
        monkeypatch,
        test_settings,
        "unchanged",
        "put",
    )
    original = f"front/{context.passenger_id}.jpg"
    derived = f"passport-crops/{context.passenger_id}/prior.jpg"
    edited = f"passport-edits/{context.passenger_id}/prior.jpg"
    await db_session.execute(
        update(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.id == context.passenger_id,
        )
        .values(image_s3_key=original)
    )
    db_session.add(
        PassportImageCropModel(
            submission_id=context.passenger_id,
            image_type="passport_front",
            active=True,
            source_storage_key=original,
            derived_storage_key=derived,
            edit_source_storage_key=edited,
            crop_x=0,
            crop_y=0,
            crop_width=1,
            crop_height=1,
            source_width=800,
            source_height=600,
        )
    )
    await db_session.commit()
    context.objects.update(
        {original: b"original-evidence", derived: b"old-crop", edited: b"old-edit"}
    )
    deleted = []

    def delete_objects(*, Delete, **_kwargs):
        for value in Delete["Objects"]:
            deleted.append(value["Key"])
            context.objects.pop(value["Key"])
        return {"Errors": []}

    monkeypatch.setattr(context.client, "delete_objects", delete_objects, raising=False)
    result = await perform_held_import(context, db_session, "put")
    assert not isinstance(result, BaseException), repr(result)
    assert result.saved_count == 1
    async with context.factory() as fresh:
        model = await fresh.get(PassportSubmissionModel, context.passenger_id)
        crop = await fresh.scalar(
            select(PassportImageCropModel).where(
                PassportImageCropModel.submission_id == context.passenger_id,
                PassportImageCropModel.image_type == "passport_front",
            )
        )
        retained = await fresh.scalar(
            select(PassportImageLibraryItemModel).where(
                PassportImageLibraryItemModel.submission_id == context.passenger_id,
                PassportImageLibraryItemModel.storage_key == original,
            )
        )
    assert retained is not None and retained.original_source_storage_key == original
    assert model.image_s3_key != original and model.image_s3_key in context.objects
    assert context.objects[original] == b"original-evidence"
    assert set(deleted) == {derived, edited}
    assert crop.revision == 2 and not crop.active
    assert crop.derived_storage_key is None and crop.edit_source_storage_key is None
