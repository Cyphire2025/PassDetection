"""Identity action redemption follows account locks and current expiry gates."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from app.infrastructure.database.models import UserModel
from app.infrastructure.repositories import identity_security_repository as repository_module
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.presentation.api.v1.routes import auth_identity
from tests.integration.test_auth_response_durability import auth_database as auth_database
from tests.integration.test_auth_response_durability import prepare_request, snapshot
from tests.integration.test_mfa_denial_durability import post


async def test_redemption_locks_account_before_action_row(db_session):
    user = UserModel(
        email="lock-order@example.invalid",
        hashed_password="unused-synthetic",
        full_name="Synthetic Lock Boundary",
        role="agency_staff",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    repository = IdentitySecurityRepository(db_session)
    locks = []

    def observe(orm_state):
        statement = orm_state.statement
        if orm_state.is_select and getattr(statement, "_for_update_arg", None) is not None:
            locks.extend(table.name for table in statement.get_final_froms())

    event.listen(db_session.sync_session, "do_orm_execute", observe)
    try:
        _, raw_token = await repository.issue_action_token(
            user_id=user.id,
            purpose="password_recovery",
            expires_in=timedelta(minutes=20),
        )
        assert locks[:2] == ["users", "identity_action_tokens"]
        locks.clear()
        token = await repository.get_valid_action_token(
            raw_token=raw_token,
            purpose="password_recovery",
        )
        assert token is not None
        assert locks[:2] == ["users", "identity_action_tokens"]
    finally:
        event.remove(db_session.sync_session, "do_orm_execute", observe)


@pytest.mark.parametrize("flow", ["activate_challenge", "recover_challenge"])
async def test_expiry_is_rechecked_after_password_work_before_consumption(
    auth_database,
    monkeypatch,
    flow,
):
    env = auth_database
    path, headers, payload = await prepare_request(env.sessions, flow)
    baseline = await snapshot(env.sessions)
    env.gate.release.set()

    class Clock(datetime):
        instant = datetime.now(UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.instant if tz is not None else cls.instant.replace(tzinfo=None)

    original_work = auth_identity.run_password_work

    async def delayed_work(function, *args, **kwargs):
        result = await original_work(function, *args, **kwargs)
        if function is auth_identity.verify_password:
            # A bounded expensive operation or database wait may cross expiry.
            # Advance only this synthetic request clock, with no wall-clock sleep.
            Clock.instant += timedelta(minutes=10)
        return result

    monkeypatch.setattr(auth_identity, "datetime", Clock)
    monkeypatch.setattr(repository_module, "datetime", Clock)
    monkeypatch.setattr(auth_identity, "run_password_work", delayed_work)

    await post(env.app, path, headers, json.loads(payload))

    assert await snapshot(env.sessions) == baseline
