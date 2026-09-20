"""Populate existing one-way source links after migration 0104 (no messages sent)."""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import or_, select

from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
)
from app.infrastructure.database.session import AsyncSessionFactory, engine
from app.infrastructure.whatsapp.source_group_sync import sync_group_broadcast_contacts


async def backfill() -> int:
    async with AsyncSessionFactory() as session:
        sources = list((await session.execute(
            select(ClientGroupModel.agency_id, ClientGroupModel.id)
            .join(ClientGroupWhatsAppBroadcastLinkModel, (
                ClientGroupWhatsAppBroadcastLinkModel.client_group_id == ClientGroupModel.id
            ) & (ClientGroupWhatsAppBroadcastLinkModel.agency_id == ClientGroupModel.agency_id))
            .where(or_(
                ClientGroupModel.import_only.is_(True),
                ClientGroupWhatsAppBroadcastLinkModel.sync_contacts_from_group.is_(True),
            )).distinct().order_by(ClientGroupModel.agency_id, ClientGroupModel.id)
        )).all())
    totals = dict.fromkeys(("groups", "broadcasts", "contacts", "added", "updated", "removed", "failed"), 0)
    for agency_id, group_id in sources:
        try:
            async with AsyncSessionFactory() as session, session.begin():
                counts = await sync_group_broadcast_contacts(
                    session, agency_id=agency_id, group_id=group_id,
                )
            totals["groups"] += 1
            for key, value in counts.items():
                totals[key] += value
        except Exception as exc:
            totals["failed"] += 1
            # Only identifiers and a stable error class/code, never phone data,
            # SQL parameter dumps, or private exception messages.
            print(json.dumps({
                "group_id": str(group_id), "error": type(exc).__name__,
                "code": getattr(exc, "code", "SOURCE_SYNC_FAILED"),
            }), flush=True)
    print(json.dumps(totals), flush=True)
    return 1 if totals["failed"] else 0


async def _main() -> int:
    try:
        return await backfill()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", action="store_true", required=True)
    parser.parse_args()
    raise SystemExit(asyncio.run(_main()))
