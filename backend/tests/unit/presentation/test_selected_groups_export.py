from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientFieldSet,
    SubmissionMatchRow,
)
from app.domain.entities.entities import (
    ClientGroup,
    GroupStatus,
    User,
    UserRole,
)
from app.presentation.api.v1.routes import passports as passports_route
from app.presentation.api.v1.schemas.passport_schemas import (
    ExportSelectedGroupsRequest,
)

NOW = datetime(2026, 7, 23, 12, tzinfo=UTC)


def _group(
    *,
    name: str,
    agency_id: uuid.UUID,
    staff_code_enabled: bool = False,
) -> ClientGroup:
    return ClientGroup(
        id=uuid.uuid4(),
        name=name,
        token=f"token-{uuid.uuid4()}",
        agency_id=agency_id,
        status=GroupStatus.ACTIVE,
        created_by_user_id=uuid.uuid4(),
        created_at=NOW,
        destination="Vietnam",
        travel_date=date(2026, 8, 12),
        return_date=date(2026, 8, 15),
        staff_code_enabled=staff_code_enabled,
    )


def _pending_match(
    *,
    name: str,
    phone: str,
    zone: str,
    staff_code: str | None = None,
) -> SubmissionMatchRow:
    recipient_id = uuid.uuid4()
    imported_fields = {"Zone Name": zone}
    if staff_code is not None:
        imported_fields["Staff Code"] = staff_code
    return SubmissionMatchRow(
        status="not_submitted",
        match_basis=None,
        normalized_phone=phone,
        recipient_ids=(recipient_id,),
        submission_ids=(),
        broadcast_ids=(uuid.uuid4(),),
        broadcast_names=("Recipients",),
        recipient_names=(name,),
        submission_names=(),
        updated_at=NOW,
        recipient_fields=(
            RecipientFieldSet(
                recipient_id=recipient_id,
                fields=imported_fields,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_selected_groups_export_combines_pending_only_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    mumbai_group = _group(name="Mumbai Group", agency_id=agency_id)
    delhi_group = _group(
        name="Delhi Group",
        agency_id=agency_id,
        staff_code_enabled=True,
    )
    groups = [mumbai_group, delhi_group]

    group_result = MagicMock()
    group_result.scalars.return_value.all.return_value = groups
    submission_result = MagicMock()
    submission_result.scalars.return_value.all.return_value = []
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [group_result, submission_result]

    match_rows = {
        mumbai_group.id: [
            _pending_match(
                name="Mumbai Pending",
                phone="+919000000002",
                zone="Mumbai-2",
            )
        ],
        delhi_group.id: [
            _pending_match(
                name="Delhi Pending",
                phone="+919000000001",
                zone="Delhi",
                staff_code="25290",
            )
        ],
    }
    monkeypatch.setattr(
        passports_route.ClientGroupRepository,
        "_to_entity",
        staticmethod(lambda model: model),
    )
    matcher = AsyncMock(return_value=match_rows)
    monkeypatch.setattr(
        passports_route,
        "_export_whatsapp_match_rows",
        matcher,
    )

    response = await passports_route.export_selected_groups(
        body=ExportSelectedGroupsRequest(
            group_ids=[mumbai_group.id, delhi_group.id],
        ),
        current_user=User(
            id=uuid.uuid4(),
            email="admin@example.test",
            hashed_password="hash",
            full_name="Admin",
            role=UserRole.AGENCY_ADMIN,
            agency_id=agency_id,
        ),
        session=session,
    )
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    content = b"".join(chunks)
    worksheet = load_workbook(io.BytesIO(content), data_only=False).active
    headers = [cell.value for cell in worksheet[4]]
    name_column = headers.index("Client Name") + 1
    zone_column = headers.index("Zone Name") + 1
    staff_code_column = headers.index("Staff Code") + 1
    pending_title_row = next(
        row
        for row in range(1, worksheet.max_row + 1)
        if worksheet.cell(row=row, column=1).value == "PENDING"
    )
    pending_rows = [
        row
        for row in range(pending_title_row + 2, worksheet.max_row + 1)
        if worksheet.cell(row=row, column=name_column).value
    ]

    assert session.execute.await_count == 2
    matcher.assert_awaited_once_with(session, [], groups=groups)
    assert [
        worksheet.cell(row=row, column=name_column).value
        for row in pending_rows
    ] == ["Delhi Pending", "Mumbai Pending"]
    assert [
        worksheet.cell(row=row, column=zone_column).value
        for row in pending_rows
    ] == ["Delhi", "Mumbai-2"]
    assert worksheet.cell(
        row=pending_rows[0],
        column=staff_code_column,
    ).value == "25290"
    assert all(
        cell.fill.fill_type == "solid" and cell.fill.fgColor.rgb == "00FFF2CC"
        for row in pending_rows
        for cell in worksheet[row]
    )
