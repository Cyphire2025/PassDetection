"""Existing device grants cannot outlive the submitted contact authority."""

from datetime import UTC, datetime

import pytest

from app.application.mobile.passenger_session_authority import (
    ensure_current_passenger_session_bindings,
)
from app.application.security.mobile_access_policy import MobileAccessPolicy
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import AuthorizationError
from tests.gc_app_workflow_fixtures import workflow_group, workflow_passenger, workflow_session


@pytest.mark.asyncio
async def test_unchanged_submitted_contacts_keep_existing_session_and_refresh_token(db_session):
    _, _, access = await workflow_group(db_session)
    submission, identity = await workflow_passenger(db_session, access)
    device, refresh = await workflow_session(db_session, [identity])
    assert await ensure_current_passenger_session_bindings(db_session, device)
    assert device.status == "active" and device.session_generation == 0
    assert refresh.revoked_at is None
    submission.client_phone = "98765 43210"
    await db_session.commit()
    assert await ensure_current_passenger_session_bindings(db_session, device)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["number", "draft", "import", "generation", "revoked"])
async def test_changed_nonselected_contact_revokes_session_durably_without_deleting_data(db_session, change):
    _, _, access = await workflow_group(db_session)
    first_submission, selected = await workflow_passenger(db_session, access)
    second_submission, other = await workflow_passenger(db_session, access)
    device, refresh = await workflow_session(db_session, [selected, other])
    if change == "number":
        second_submission.client_phone = "+919876543211"
    elif change == "draft":
        second_submission.client_reviewed_at = None
    elif change == "import":
        second_submission.confidence_score = {"source": "excel_import"}
    elif change == "generation":
        other.claim_generation += 1
    else:
        other.status = "revoked"
        other.revoked_at = datetime.now(UTC)
    await db_session.commit()
    assert not await ensure_current_passenger_session_bindings(db_session, device)
    await db_session.rollback()  # A denied request must not undo the revocation.
    await db_session.refresh(device)
    await db_session.refresh(refresh)
    assert device.status == "revoked" and device.session_generation == 1
    assert refresh.revoked_at is not None
    assert selected.status == "eligible"
    assert await db_session.get(type(first_submission), first_submission.id) is not None
    assert await db_session.get(type(second_submission), second_submission.id) is not None


@pytest.mark.asyncio
async def test_direct_trip_policy_rejects_old_broadcast_phone_after_contact_policy_change(db_session):
    _, group, access = await workflow_group(db_session)
    submission, identity = await workflow_passenger(db_session, access)
    device, _ = await workflow_session(db_session, [identity])
    claims = MobileAccessClaims(
        principal_id=identity.id, account_id=device.account_id, principal_type="passenger",
        agency_id=device.agency_id, session_id=device.id, session_generation=0,
        password_change_required=False, expires_at=int(device.expires_at.timestamp()),
    )
    policy = MobileAccessPolicy(db_session)
    assert (await policy.require_trip_access(claims, group.id)).passenger_identity == identity
    submission.client_phone = "+919876543211"
    await db_session.commit()
    with pytest.raises(AuthorizationError):
        await policy.require_trip_access(claims, group.id)
