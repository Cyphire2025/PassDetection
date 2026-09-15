"""Public completion provenance cannot be supplied by imported/staff metadata."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.application.mobile.passenger_phone_authority import authoritative_submission_phone
from app.application.use_cases.passports.correct_client_details import correct_client_details
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.client_collection_provenance import (
    CLIENT_COLLECTION_SUBMITTED_KEY as KEY,
)
from app.domain.value_objects.client_collection_provenance import (
    CLIENT_COLLECTION_SUBMITTED_VALUE as VALUE,
)
from app.infrastructure.imports.passport_excel_importer import PassportExcelImporter
from app.presentation.api.v1.routes.passport_excel_import_support import (
    _apply_passport_excel_row_to_submission,
)
from tests.unit.application.test_correct_client_details import sample
from tests.unit.application.test_manual_passport_staff_review import _draft, _submit
from tests.unit.presentation.test_passport_excel_import_route import (
    _existing_submission,
    _imported_row,
)


async def test_successful_public_submission_stamps_marker_and_replay_preserves_it():
    group, submission, use_case, passports, _ = _draft()
    result = await _submit(group, submission, use_case)
    assert submission.staff_metadata[KEY] == VALUE
    assert result.staff_metadata[KEY] == VALUE
    assert authoritative_submission_phone(submission) == "+919876543210"
    replay = await _submit(group, submission, use_case)
    assert replay.idempotent_replay and replay.staff_metadata[KEY] == VALUE
    passports.update.assert_awaited_once()


async def test_rejected_public_document_does_not_gain_completion_provenance():
    group, submission, use_case, _, _ = _draft("not_passport")
    with pytest.raises(ValidationError):
        await _submit(group, submission, use_case)
    assert KEY not in (submission.staff_metadata or {})


def test_staff_cannot_patch_marker_but_contact_correction_preserves_existing_provenance():
    submission, group = sample()
    with pytest.raises(ValidationError):
        correct_client_details(submission, group, {KEY: VALUE})
    submission.staff_metadata[KEY] = VALUE
    updated, _ = correct_client_details(submission, group, {"client_phone": "9876543211"})
    assert updated.staff_metadata[KEY] == VALUE


def test_excel_header_cannot_allocate_reserved_completion_key():
    headers = PassportExcelImporter()._metadata_headers(
        (KEY, "Client collection submitted", "Name")
    )
    assert KEY not in headers.values()


@pytest.mark.parametrize("existing_marker", [False, True])
@pytest.mark.parametrize("new_phone", [None, "98765 43210", "+919876543211"])
def test_excel_merge_never_forges_marker_and_replacing_phone_removes_old_authority(
    existing_marker, new_phone
):
    submission = _existing_submission(name="Synthetic", passport_number="P1234567")
    submission.client_phone = "+919876543210"
    if existing_marker:
        submission.staff_metadata[KEY] = VALUE
    row = replace(_imported_row(), client_phone=new_phone, staff_metadata={KEY: VALUE})
    _apply_passport_excel_row_to_submission(submission, row, now=datetime.now(UTC))
    expected = existing_marker and new_phone != "+919876543211"
    assert ((submission.staff_metadata or {}).get(KEY) == VALUE) is expected


@pytest.mark.parametrize("known_import", [False, True])
@pytest.mark.parametrize("new_phone", [None, "98765 43210", "+919876543211"])
def test_legacy_preimport_authority_is_preserved_only_for_unchanged_public_contact(
    known_import, new_phone
):
    submission = _existing_submission(name="Synthetic", passport_number="P1234567")
    submission.client_phone = "+919876543210"
    submission.client_reviewed_at = datetime.now(UTC)
    submission.status = "needs_review"
    submission.image_s3_key = "synthetic/public.jpg"
    submission.confidence_score = {"source": "excel_import"} if known_import else None
    row = replace(_imported_row(), client_phone=new_phone, staff_metadata={KEY: VALUE})
    _apply_passport_excel_row_to_submission(submission, row, now=datetime.now(UTC))
    expected = not known_import and new_phone != "+919876543211"
    assert ((submission.staff_metadata or {}).get(KEY) == VALUE) is expected
    assert (authoritative_submission_phone(submission) is not None) is expected
    assert submission.confidence_score["source"] == "excel_import"
