from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, UploadFile, status
from sqlalchemy.dialects import postgresql

from app.presentation.api.v1.routes import passports


def _imported_row(
    *,
    row_number: int = 2,
    name: str = "Asha Rao",
    passport_number: str | None = "P1234567",
    staff_code: str | None = None,
    surname: str = "Rao",
) -> passports.ImportedPassportRow:
    confirmed_fields = {"given_names": name.split()[0], "surname": surname}
    if passport_number is not None:
        confirmed_fields["passport_number"] = passport_number
    if staff_code is not None:
        confirmed_fields["staff_code"] = staff_code
    metadata = {"source_sheet": "Passengers", "source_zone": "Passengers"}
    if staff_code is not None:
        metadata["staff_code"] = staff_code
    return passports.ImportedPassportRow(
        row_number=row_number,
        worksheet_name="Passengers",
        client_name=name,
        client_email=None,
        client_phone=None,
        departure_city=None,
        nearest_domestic_airport=None,
        confirmed_fields=confirmed_fields,
        staff_metadata=metadata,
    )


def _existing_submission(
    *,
    name: str,
    passport_number: str | None,
    staff_code: str | None = None,
) -> SimpleNamespace:
    fields: dict[str, str] = {}
    if passport_number is not None:
        fields["passport_number"] = passport_number
    metadata = {"staff_code": staff_code} if staff_code is not None else {}
    return SimpleNamespace(
        id=uuid.uuid4(),
        client_name=name,
        client_email=None,
        client_phone=None,
        departure_city=None,
        nearest_domestic_airport=None,
        confirmed_fields=dict(fields),
        extracted_fields=dict(fields),
        staff_metadata=metadata,
        confidence_score=None,
        overall_confidence=None,
        updated_at=None,
    )


@pytest.mark.asyncio
async def test_excel_upload_reader_accepts_exact_limit_and_rejects_one_byte_over() -> None:
    accepted = UploadFile(file=BytesIO(b"x" * 32), filename="passengers.xlsx")
    assert (
        await passports._read_bounded_passport_excel_upload(
            accepted,
            max_bytes=32,
        )
        == b"x" * 32
    )

    oversized = UploadFile(file=BytesIO(b"x" * 33), filename="passengers.xlsx")
    with pytest.raises(HTTPException) as exc_info:
        await passports._read_bounded_passport_excel_upload(
            oversized,
            max_bytes=32,
        )

    assert exc_info.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert exc_info.value.detail.startswith("The Excel file is too large")


@pytest.mark.asyncio
async def test_excel_parser_is_offloaded_from_the_async_request_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, tuple[Any, ...]]] = []

    class StubImporter:
        def import_rows(self, content: bytes) -> list[str]:
            assert content == b"workbook"
            return ["parsed"]

    async def fake_to_thread(function: Any, *args: Any) -> Any:
        calls.append((function, args))
        return function(*args)

    monkeypatch.setattr(passports, "PassportExcelImporter", StubImporter)
    monkeypatch.setattr(passports.asyncio, "to_thread", fake_to_thread)

    result = await passports._parse_passport_excel_rows(b"workbook")

    assert result == ["parsed"]
    assert len(calls) == 1
    assert calls[0][1] == (b"workbook",)


@pytest.mark.asyncio
async def test_excel_group_import_lock_is_tenant_scoped_and_for_update() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()

    class CapturingSession:
        statement: Any = None

        async def scalar(self, statement: Any) -> uuid.UUID:
            self.statement = statement
            return group_id

    session = CapturingSession()

    assert await passports._lock_passport_excel_group_import(
        session,  # type: ignore[arg-type]
        group_id=group_id,
        agency_id=agency_id,
    )

    sql = str(
        session.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    assert "CLIENT_GROUPS.ID" in sql
    assert "CLIENT_GROUPS.AGENCY_ID" in sql
    assert "FOR UPDATE" in sql


def test_canonical_passport_match_updates_legacy_generic_name_without_duplication() -> None:
    existing = _existing_submission(
        name="Legacy Generic Name",
        passport_number="z 47-79216",
    )
    row = _imported_row(
        name="UMESHBHAI AMRUTBHAI MAHYAVANSHI",
        passport_number="Z4779216",
        surname="MAHYAVANSHI",
    )

    indexes = passports._build_passport_excel_existing_indexes([existing])
    resolved = passports._resolve_existing_passport_excel_submission(row, indexes)

    assert resolved is existing
    passports._apply_passport_excel_row_to_submission(
        existing,
        row,
        now=datetime.now(tz=UTC),
    )
    assert existing.client_name == "UMESHBHAI AMRUTBHAI MAHYAVANSHI"
    assert existing.confirmed_fields["passport_number"] == "Z4779216"


@pytest.mark.parametrize("duplicate_key", ["passport", "staff"])
def test_existing_duplicate_strong_keys_fail_closed(duplicate_key: str) -> None:
    first = _existing_submission(
        name="First Person",
        passport_number="P1234567" if duplicate_key == "passport" else "P1111111",
        staff_code="S-42" if duplicate_key == "staff" else "S-1",
    )
    second = _existing_submission(
        name="Second Person",
        passport_number="P-1234567" if duplicate_key == "passport" else "P2222222",
        staff_code="s-42" if duplicate_key == "staff" else "S-2",
    )

    with pytest.raises(passports._PassportExcelImportConflict, match="Multiple existing"):
        passports._build_passport_excel_existing_indexes([first, second])


def test_staff_and_passport_matches_to_different_existing_people_fail_closed() -> None:
    passport_owner = _existing_submission(
        name="Passport Owner",
        passport_number="P1111111",
        staff_code="STAFF-1",
    )
    staff_owner = _existing_submission(
        name="Staff Owner",
        passport_number="P2222222",
        staff_code="STAFF-2",
    )
    indexes = passports._build_passport_excel_existing_indexes([passport_owner, staff_owner])
    conflicting_row = _imported_row(
        name="Conflicting Person",
        passport_number="P1111111",
        staff_code="STAFF-2",
    )

    with pytest.raises(
        passports._PassportExcelImportConflict,
        match="identify different existing passengers",
    ):
        passports._resolve_existing_passport_excel_submission(
            conflicting_row,
            indexes,
        )


@pytest.mark.parametrize(
    ("existing_passport", "existing_staff", "row_passport", "row_staff", "message"),
    [
        ("P1234567", "S-OLD", "P1234567", "S-NEW", "staff code conflicts"),
        ("P-OLD-123", "S-42", "P-NEW-456", "S-42", "passport number conflicts"),
    ],
)
def test_one_matching_strong_key_cannot_overwrite_another_stored_key(
    existing_passport: str,
    existing_staff: str,
    row_passport: str,
    row_staff: str,
    message: str,
) -> None:
    existing = _existing_submission(
        name="Existing Passenger",
        passport_number=existing_passport,
        staff_code=existing_staff,
    )
    indexes = passports._build_passport_excel_existing_indexes([existing])
    row = _imported_row(
        name="Imported Passenger",
        passport_number=row_passport,
        staff_code=row_staff,
    )

    with pytest.raises(passports._PassportExcelImportConflict, match=message):
        passports._resolve_existing_passport_excel_submission(row, indexes)


def test_partial_reimport_preserves_optional_contact_and_organisational_details() -> None:
    existing = _existing_submission(
        name="Existing Passenger",
        passport_number="P1234567",
        staff_code="S-42",
    )
    existing.client_email = "existing@example.com"
    existing.client_phone = "+919876543210"
    existing.departure_city = "Delhi"
    existing.nearest_domestic_airport = "DEL"
    existing.staff_metadata.update(
        {
            "designation": "Manager",
            "agent_code": "AG-9",
            "source_sheet": "Old sheet",
            "source_zone": "Old zone",
        }
    )
    row = _imported_row(
        name="Updated Passenger",
        passport_number="P1234567",
        staff_code=None,
    )

    passports._apply_passport_excel_row_to_submission(
        existing,
        row,
        now=datetime.now(tz=UTC),
    )

    assert existing.client_email == "existing@example.com"
    assert existing.client_phone == "+919876543210"
    assert existing.departure_city == "Delhi"
    assert existing.nearest_domestic_airport == "DEL"
    assert existing.staff_metadata["designation"] == "Manager"
    assert existing.staff_metadata["agent_code"] == "AG-9"
    assert existing.staff_metadata["staff_code"] == "S-42"
    assert existing.staff_metadata["source_sheet"] == "Passengers"
    assert existing.staff_metadata["source_zone"] == "Passengers"


def test_reviewed_passport_identity_outranks_conflicting_ocr_value() -> None:
    existing = _existing_submission(
        name="Reviewed Passenger",
        passport_number="P1234567",
    )
    existing.extracted_fields["passport_number"] = "P1284567"
    indexes = passports._build_passport_excel_existing_indexes([existing])
    row = _imported_row(
        name="Reviewed Passenger",
        passport_number="P1234567",
    )

    resolved = passports._resolve_existing_passport_excel_submission(row, indexes)

    assert resolved is existing


def test_reimport_recomputes_only_remaining_extraction_conflicts() -> None:
    existing = _existing_submission(
        name="Reviewed Passenger",
        passport_number="P1234567",
    )
    existing.confirmed_fields["nationality"] = "INDIA"
    existing.extracted_fields.update(
        {
            "passport_number": "P1284567",
            "nationality": "NEPAL",
        }
    )
    existing.extraction_conflicts = [
        {"field": "passport_number", "status": "mismatch"},
        {"field": "nationality", "status": "mismatch"},
    ]
    row = _imported_row(
        name="Reviewed Passenger",
        passport_number="P1234567",
    )

    passports._apply_passport_excel_row_to_submission(
        existing,
        row,
        now=datetime.now(tz=UTC),
    )

    assert existing.extracted_fields["passport_number"] == "P1234567"
    assert [conflict["field"] for conflict in existing.extraction_conflicts] == [
        "nationality"
    ]


def test_conflicting_duplicate_passport_rows_in_workbook_fail_closed() -> None:
    first = _imported_row(
        row_number=2,
        name="Asha Rao",
        passport_number="P1234567",
    )
    second = _imported_row(
        row_number=3,
        name="Different Person",
        passport_number="P-1234567",
        surname="Person",
    )

    with pytest.raises(
        passports._PassportExcelImportConflict,
        match="same passport number.*conflicting passenger details",
    ):
        passports._deduplicate_passport_excel_rows([first, second])


def test_deduplication_handles_many_same_name_rows_in_linear_indexed_time() -> None:
    rows = [
        _imported_row(
            row_number=index + 2,
            name="Shared Passenger Name",
            passport_number=f"P{index:07d}",
            surname="Name",
        )
        for index in range(10_000)
    ]

    assert passports._deduplicate_passport_excel_rows(rows) == rows


def test_weak_identity_conflicts_with_any_prior_strong_identity_variant() -> None:
    first = _imported_row(
        row_number=2,
        name="Shared Passenger Name",
        passport_number="P0000001",
        surname="Name",
    )
    second = _imported_row(
        row_number=3,
        name="Shared Passenger Name",
        passport_number="P0000002",
        surname="Name",
    )
    weak = _imported_row(
        row_number=4,
        name="Shared Passenger Name",
        passport_number=None,
        surname="Name",
    )

    with pytest.raises(
        passports._PassportExcelImportConflict,
        match="ambiguous passenger identity",
    ):
        passports._deduplicate_passport_excel_rows([first, second, weak])


def test_excel_merge_allows_only_explicit_surname_to_clear() -> None:
    merged = passports._merge_excel_fields(
        {
            "surname": "Old Surname",
            "nationality": "INDIAN",
            "place_of_issue": "Mumbai",
        },
        {
            "surname": "",
            "nationality": "",
            "place_of_issue": None,
        },
    )

    assert merged == {
        "surname": "",
        "nationality": "INDIAN",
        "place_of_issue": "Mumbai",
    }


@pytest.mark.asyncio
async def test_locked_reauthorization_refreshes_user_group_and_policy_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    user_id = uuid.uuid4()
    refreshed_user = SimpleNamespace(
        id=user_id,
        agency_id=agency_id,
        role=passports.UserRole.AGENCY_ADMIN,
        is_active=True,
    )
    refreshed_group = SimpleNamespace(id=group_id, agency_id=agency_id)

    async def fake_lock(*args: Any, **kwargs: Any) -> bool:
        events.append("lock")
        return True

    class StubUserRepository:
        def __init__(self, session: Any) -> None:
            pass

        async def get_by_id(self, requested_user_id: uuid.UUID) -> Any:
            assert requested_user_id == user_id
            events.append("user")
            return refreshed_user

    class StubGroupRepository:
        def __init__(self, session: Any) -> None:
            pass

        async def get_by_id(self, requested_group_id: uuid.UUID) -> Any:
            assert requested_group_id == group_id
            events.append("group")
            return refreshed_group

    class StubAuthorizationPolicy:
        def __init__(self, session: Any) -> None:
            pass

        async def require_export_data(self, user: Any, group: Any) -> None:
            assert user is refreshed_user
            assert group is refreshed_group
            events.append("authorize")

    monkeypatch.setattr(passports, "_lock_passport_excel_group_import", fake_lock)
    monkeypatch.setattr(passports, "UserRepository", StubUserRepository)
    monkeypatch.setattr(passports, "ClientGroupRepository", StubGroupRepository)
    monkeypatch.setattr(passports, "AuthorizationPolicy", StubAuthorizationPolicy)

    user, group = await passports._lock_and_reauthorize_passport_excel_import(
        object(),  # type: ignore[arg-type]
        group_id=group_id,
        expected_agency_id=agency_id,
        user_id=user_id,
    )

    assert user is refreshed_user
    assert group is refreshed_group
    assert events == ["lock", "user", "group", "authorize"]


@pytest.mark.asyncio
async def test_locked_reauthorization_fails_closed_after_user_agency_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async def fake_lock(*args: Any, **kwargs: Any) -> bool:
        return True

    class StubUserRepository:
        def __init__(self, session: Any) -> None:
            pass

        async def get_by_id(self, requested_user_id: uuid.UUID) -> Any:
            assert requested_user_id == user_id
            return SimpleNamespace(
                id=user_id,
                agency_id=uuid.uuid4(),
                role=passports.UserRole.AGENCY_ADMIN,
                is_active=True,
            )

    class StubGroupRepository:
        def __init__(self, session: Any) -> None:
            pass

        async def get_by_id(self, requested_group_id: uuid.UUID) -> Any:
            assert requested_group_id == group_id
            return SimpleNamespace(id=group_id, agency_id=expected_agency_id)

    monkeypatch.setattr(passports, "_lock_passport_excel_group_import", fake_lock)
    monkeypatch.setattr(passports, "UserRepository", StubUserRepository)
    monkeypatch.setattr(passports, "ClientGroupRepository", StubGroupRepository)

    with pytest.raises(HTTPException) as exc_info:
        await passports._lock_and_reauthorize_passport_excel_import(
            object(),  # type: ignore[arg-type]
            group_id=group_id,
            expected_agency_id=expected_agency_id,
            user_id=user_id,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_route_releases_read_transaction_before_cpu_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    user_id = uuid.uuid4()
    initial_group = SimpleNamespace(id=group_id, agency_id=agency_id)
    current_user = SimpleNamespace(
        id=user_id,
        agency_id=agency_id,
        role=passports.UserRole.AGENCY_ADMIN,
    )

    class StubSession:
        async def rollback(self) -> None:
            events.append("rollback")

    class StubGroupRepository:
        def __init__(self, session: Any) -> None:
            pass

        async def get_by_id(self, requested_group_id: uuid.UUID) -> Any:
            assert requested_group_id == group_id
            events.append("initial_group")
            return initial_group

    class StubAuthorizationPolicy:
        def __init__(self, session: Any) -> None:
            pass

        async def require_export_data(self, user: Any, group: Any) -> None:
            events.append("initial_authorize")

    async def fake_read(*args: Any, **kwargs: Any) -> bytes:
        events.append("read")
        return b"workbook"

    async def fake_parse(content: bytes) -> list[Any]:
        assert content == b"workbook"
        events.append("parse")
        return []

    async def fail_locked_reauthorization(*args: Any, **kwargs: Any) -> Any:
        events.append("locked_reauthorize")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    monkeypatch.setattr(passports, "ClientGroupRepository", StubGroupRepository)
    monkeypatch.setattr(passports, "AuthorizationPolicy", StubAuthorizationPolicy)
    monkeypatch.setattr(passports, "_read_bounded_passport_excel_upload", fake_read)
    monkeypatch.setattr(passports, "_parse_passport_excel_rows", fake_parse)
    monkeypatch.setattr(
        passports,
        "_lock_and_reauthorize_passport_excel_import",
        fail_locked_reauthorization,
    )

    with pytest.raises(HTTPException) as exc_info:
        await passports.import_passports_by_group(
            group_id=group_id,
            file=UploadFile(file=BytesIO(b"x"), filename="passengers.xlsx"),
            current_user=current_user,
            session=StubSession(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert events == [
        "initial_group",
        "initial_authorize",
        "rollback",
        "read",
        "parse",
        "locked_reauthorize",
        "rollback",
    ]
