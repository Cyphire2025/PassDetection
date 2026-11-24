"""Keep routing metadata separate from the live external authorization barriers."""

from collections.abc import Sequence


def assert_external_read_authority(statements: Sequence[str], *, row_locks: bool = False) -> None:
    """A routing probe adds one query, never business data or a substitute for locks."""
    sql = [" ".join(statement.lower().split()) for statement in statements]
    assert len(sql) >= 4, sql
    assert sql[0].split(" from ")[0] == (
        "select mcp_grants.client_id, mcp_grants.user_id, mcp_grants.security_version"
    ), sql[0]
    assert " from mcp_grants " in sql[0] and " for " not in sql[0], sql[0]
    assert sql[1].startswith("select mcp_control.enabled from mcp_control "), sql[1]
    assert sql[2].startswith("select mcp_grants.id,") and " from mcp_grants " in sql[2], sql[2]
    assert " from users join user_security_states " in sql[3], sql[3]
    if row_locks:
        assert " for share" in sql[1], sql[1]
        assert " for update" in sql[2], sql[2]
        assert " for share of users, user_security_states" in sql[3], sql[3]
