from __future__ import annotations

import inspect

from app.infrastructure.imports.passport_document_importer import PassportDocumentImporter
from app.presentation.api.v1.routes import admin, client_groups, passports


def test_both_staff_import_paths_version_sources_and_tombstone_existing_crops() -> None:
    preview_source = inspect.getsource(passports._passport_document_preview)
    importer_source = inspect.getsource(PassportDocumentImporter.collect)
    assert "PassportDocumentImporter().collect" in preview_source
    assert "self._collect_zip(" in importer_source
    assert "self._collect_direct(" in importer_source

    unified_save_source = inspect.getsource(passports.save_passport_documents_by_group)
    assert "_passport_document_preview(" in unified_save_source
    assert ".with_for_update()" in unified_save_source
    assert "uuid.uuid4().hex" in unified_save_source
    assert "crop_repo.reset(" in unified_save_source
    assert "replaced_crop_keys" in unified_save_source
    assert "library_repo.ensure_original(" in unified_save_source
    assert "_delete_unreferenced_passport_image_keys_best_effort(" in unified_save_source

    cleanup_source = inspect.getsource(
        passports._delete_unreferenced_passport_image_keys_best_effort
    )
    assert "referenced_storage_keys" in cleanup_source
    assert "passport_import_replaced_object_cleanup_deferred" in cleanup_source


def test_permanent_deletion_paths_collect_crop_derivatives() -> None:
    for source in (
        inspect.getsource(passports.bulk_delete_passport_submissions),
        inspect.getsource(client_groups.permanently_delete_client_group),
        inspect.getsource(admin.delete_manager),
        inspect.getsource(admin.purge_passport_data),
    ):
        assert "derived_storage_keys" in source
        assert "edit_storage_keys" in source


def test_crop_routes_do_not_mutate_original_storage_keys() -> None:
    update_source = inspect.getsource(passports.update_passport_image_crop)
    reset_source = inspect.getsource(passports.reset_passport_image_crop)
    assert "passport-crops/" in update_source
    assert "upload_file" in update_source
    assert "image_s3_key =" not in update_source
    assert "passport_photo_s3_key =" not in update_source
    assert "passport_back_s3_key =" not in update_source
    assert "upload_file" not in reset_source
