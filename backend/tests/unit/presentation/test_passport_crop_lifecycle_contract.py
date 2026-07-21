from __future__ import annotations

import inspect

from app.presentation.api.v1.routes import admin, client_groups, passports


def test_both_staff_import_paths_version_sources_and_tombstone_existing_crops() -> None:
    zip_source = inspect.getsource(passports.save_passport_documents_by_group)
    loose_source = inspect.getsource(passports._save_loose_passport_documents_by_group)
    for source in (zip_source, loose_source):
        assert ".with_for_update()" in source
        assert "uuid.uuid4().hex" in source
        assert "crop_repo.reset(" in source
        assert "replaced_crop_keys" in source
        assert "passport_import_replaced_object_cleanup_deferred" in source


def test_permanent_deletion_paths_collect_crop_derivatives() -> None:
    assert "derived_storage_keys" in inspect.getsource(passports.bulk_delete_passport_submissions)
    assert "derived_storage_keys" in inspect.getsource(client_groups.permanently_delete_client_group)
    assert "derived_storage_keys" in inspect.getsource(admin.delete_manager)
    assert "derived_storage_keys" in inspect.getsource(admin.purge_passport_data)


def test_crop_routes_do_not_mutate_original_storage_keys() -> None:
    update_source = inspect.getsource(passports.update_passport_image_crop)
    reset_source = inspect.getsource(passports.reset_passport_image_crop)
    assert "passport-crops/" in update_source
    assert "upload_file" in update_source
    assert "image_s3_key =" not in update_source
    assert "passport_photo_s3_key =" not in update_source
    assert "passport_back_s3_key =" not in update_source
    assert "upload_file" not in reset_source
