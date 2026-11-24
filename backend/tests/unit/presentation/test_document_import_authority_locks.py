"""Actual ORM locks occur after native work in actor/scope/target order."""

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql

from tests.unit.presentation.document_import_authority_fixture import (
    perform_held_import,
    prepare_authority_import,
)


@pytest.mark.parametrize("transition", ["unchanged", "assigned_staff_unchanged"])
async def test_import_locks_current_authority_before_targets_after_put(
    db_session,
    monkeypatch,
    test_settings,
    transition,
):
    context = await prepare_authority_import(
        db_session,
        monkeypatch,
        test_settings,
        transition,
        "put",
    )
    observed = []

    def capture(state):
        statement = state.statement
        if getattr(statement, "_for_update_arg", None) is None:
            return
        sql = str(statement.compile(dialect=postgresql.dialect()))
        for table in [
            "users",
            "user_security_states",
            "client_groups",
            "manager_group_access",
            "passport_submissions",
        ]:
            if "FOR UPDATE OF " + table in sql:
                observed.append((table, context.barrier.completed.is_set(), sql))

    event.listen(db_session.sync_session, "do_orm_execute", capture)
    try:
        result = await perform_held_import(context, db_session, "put")
    finally:
        event.remove(db_session.sync_session, "do_orm_execute", capture)
    assert not isinstance(result, BaseException), repr(result)
    expected = ["users", "user_security_states", "client_groups"]
    if transition == "assigned_staff_unchanged":
        expected.append("manager_group_access")
    expected.append("passport_submissions")
    assert [table for table, _, _ in observed] == expected
    assert all(completed for _, completed, _ in observed), "A row lock preceded held external PUT"
    target_sql = observed[-1][2]
    assert "passport_submissions.group_id =" in target_sql
    assert "passport_submissions.agency_id =" in target_sql
    assert "ORDER BY passport_submissions.id" in target_sql
