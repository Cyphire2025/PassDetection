"""Read-only, tenant-explicit ownership audit before/after migration 0130.

Usage from backend:
  python scripts/audit_company_assignments.py --agency-id UUID --url-env LOCAL_AUDIT_DATABASE_URL

The named environment variable must contain an async SQLAlchemy database URL.
URLs and credentials are never printed. Output contains aggregate counts and
at most 100 group IDs per issue category, no names or passport information.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def audit(agency_id: uuid.UUID, url: str) -> dict[str, object]:
    engine = create_async_engine(url, echo=False)
    parameters = {"agency_id": str(agency_id)}
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            has_company = bool(await connection.scalar(text("""
                SELECT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema = current_schema() AND table_name = 'client_groups' AND column_name = 'company_id')
            """)))
            assignments = "g.company_id" if has_company else "a.client_organization_id"
            checks = {
                "unassigned_groups": f"{assignments} IS NULL",
                "invalid_gc_reference": "a.client_organization_id IS NOT NULL AND gc_company.id IS NULL",
                "inactive_company_assignment": "c.status = 'inactive'",
                "deleted_company_assignment": "c.status = 'deleted'",
            }
            if has_company:
                checks["invalid_core_reference"] = "g.company_id IS NOT NULL AND c.id IS NULL"
                checks["conflicting_core_gc_assignment"] = (
                    "a.client_organization_id IS NOT NULL AND g.company_id IS DISTINCT FROM a.client_organization_id"
                )
            result: dict[str, object] = {"agency_id": str(agency_id), "canonical_schema_present": has_company}
            # All SQL structure below is from fixed constants; tenant ID is a
            # bound parameter and never interpolated into SQL or identifiers.
            base = f"""
                FROM client_groups g
                LEFT JOIN gc_group_access a ON a.group_id = g.id AND a.agency_id = g.agency_id
                LEFT JOIN client_organizations gc_company ON gc_company.id = a.client_organization_id AND gc_company.agency_id = g.agency_id
                LEFT JOIN client_organizations c ON c.id = {assignments} AND c.agency_id = g.agency_id
                WHERE g.agency_id = CAST(:agency_id AS uuid) AND g.status != 'deleted'
            """
            for label, predicate in checks.items():
                count = int(await connection.scalar(text(f"SELECT count(*) {base} AND ({predicate})"), parameters) or 0)
                sample = list((await connection.scalars(text(
                    f"SELECT CAST(g.id AS text) {base} AND ({predicate}) ORDER BY g.id LIMIT 100"
                ), parameters)).all()) if count else []
                result[label] = {"count": count, "sample_group_ids": sample, "sample_is_complete": count <= 100}
            return result
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agency-id", type=uuid.UUID, required=True)
    parser.add_argument("--url-env", required=True)
    args = parser.parse_args()
    url = os.environ.get(args.url_env)
    if not url or not url.startswith("postgresql+asyncpg://"):
        parser.error("The named variable must contain an explicit PostgreSQL asyncpg URL")
    print(json.dumps(asyncio.run(audit(args.agency_id, url)), indent=2))


if __name__ == "__main__":
    main()
