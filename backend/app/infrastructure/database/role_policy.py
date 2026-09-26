"""Reject privileged identities on production runtime connections.

Migrations and provisioning use separate engines, not the request/worker pool.
The query checks effective privileges as well as role flags and memberships:
NOSUPERUSER alone is insufficient when a role owns tables or can SET ROLE.
"""

from collections.abc import Sequence

RUNTIME_ROLE_QUERY = """
SELECT
    NOT (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls),
    NOT EXISTS (SELECT 1 FROM pg_auth_members WHERE member = r.oid),
    NOT has_schema_privilege(current_user, 'public', 'CREATE'),
    NOT has_database_privilege(current_user, current_database(), 'CREATE'),
    NOT EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relowner = r.oid
    ),
    NOT has_table_privilege(current_user, 'public.audit_logs', 'UPDATE,DELETE,TRUNCATE')
        AND NOT has_any_column_privilege(current_user, 'public.audit_logs', 'UPDATE'),
    NOT has_table_privilege(current_user, 'public.alembic_version', 'INSERT,UPDATE,DELETE,TRUNCATE')
        AND NOT has_any_column_privilege(current_user, 'public.alembic_version', 'INSERT,UPDATE')
FROM pg_roles r WHERE rolname = current_user
"""


def require_runtime_role(result: Sequence[object] | None) -> None:
    if result is None or len(result) != 7 or not all(value is True for value in result):
        # Never include role names, credentials or SQL/connection details.
        raise RuntimeError(
            "Production database runtime identity is overprivileged; "
            "provision and verify the restricted runtime role before activation"
        )
