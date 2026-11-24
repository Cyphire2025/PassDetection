"""Synthetic multi-tenant workload fixtures for the fixed local QA stack only.

Creates new records under a random run identifier. Never resets a table, changes
an existing user, contacts a provider, or removes data. Session issuance is a
test fixture, not evidence that authentication was exercised by the load lane.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re

from app.infrastructure.database.session import engine
from capacity_fixture_contract import LARGE_GROUP as LARGE_GROUP
from capacity_fixture_contract import SMALL_GROUP as SMALL_GROUP
from capacity_fixture_contract import TENANTS as TENANTS
from capacity_fixture_contract import identifier as identifier
from capacity_fixture_jobs import queue_retries as queue_retries
from capacity_fixture_jobs import verify as verify
from capacity_fixture_observer import observe as observe
from capacity_fixture_seed import seed as seed
from qualification_application_journey import isolated


async def main() -> None:
    isolated()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["seed", "queues", "observe", "verify"])
    parser.add_argument("run_id")
    parser.add_argument("--seconds", type=int, default=240)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{32}", args.run_id) or not 1 <= args.seconds <= 1800:
        raise RuntimeError("A bounded synthetic run identifier/duration is required")
    try:
        if args.action == "observe":
            await observe(args.run_id, args.seconds)
        else:
            operation = {"seed": seed, "queues": queue_retries, "verify": verify}[args.action]
            print(json.dumps(await operation(args.run_id)), flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
