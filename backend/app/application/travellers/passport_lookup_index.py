"""Resumable derived lookup backfill; bounded memory, no identity/history edits."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.services.traveller_verification import exact_passport_number
from app.infrastructure.database.traveller_reuse_models import TravellerPassportModel
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


async def backfill_passport_lookup(session: AsyncSession, crypto: TravellerReuseCrypto,
    *, batch_size: int = 100,
) -> int:
    model = TravellerPassportModel
    rows = list((await session.scalars(select(model).where(
        model.number_lookup_fingerprint.is_(None), model.fingerprint_key_version == crypto.key_version,
    ).order_by(model.id).limit(min(max(batch_size, 1), 500)).with_for_update(skip_locked=True))).all())
    for row in rows:
        row.number_lookup_fingerprint = crypto.scoped_digest("passport-number", row.agency_id,
            row.company_id, exact_passport_number(crypto.decrypt(row.number_ciphertext)))
    await session.flush()
    return len(rows)
