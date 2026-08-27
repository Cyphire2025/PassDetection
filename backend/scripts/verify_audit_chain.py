"""Verify one tenant audit hash chain without printing audit record contents."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid

from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the tamper-evident audit chain for one tenant scope",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--agency-id", type=uuid.UUID)
    scope.add_argument(
        "--global-scope",
        action="store_true",
        help="Verify records whose tenant scope is intentionally global",
    )
    return parser.parse_args()


async def _verify(agency_id: uuid.UUID | None) -> int:
    async with AsyncSessionFactory() as session:
        result = await AuditLogRepository(session).verify_chain(agency_id)
    print(
        json.dumps(
            {
                "scope_key": result.scope_key,
                "valid": result.valid,
                "verified_entries": result.verified_entries,
                "first_invalid_sequence": result.first_invalid_sequence,
                "reason": result.reason,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if result.valid else 1


def main() -> int:
    args = _arguments()
    return asyncio.run(_verify(None if args.global_scope else args.agency_id))


if __name__ == "__main__":
    raise SystemExit(main())
