"""Bounded blind prefix indexes and canonical keys used only in worker memory.

At most 255 name characters yield at most 254 prefix tokens, each a tenant-keyed
32-byte HMAC. Queries intersect at most eight word prefixes, never decrypt rows.
Alphabetical ranks reveal relative order, not a plaintext spelling.
"""

import uuid

from app.domain.services.traveller_identity import normalize_name
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

MAX_NAME_CHARACTERS = 255
MAX_PREFIX_CHARACTERS = 32
MAX_QUERY_WORDS = 8


def name_order_key(name: str, person_id: uuid.UUID) -> tuple[str, str]:
    return normalize_name(name)[:MAX_NAME_CHARACTERS], str(person_id)


def prefix_digests(name: str, agency_id: uuid.UUID, company_id: uuid.UUID,
    crypto: TravellerReuseCrypto,
) -> set[bytes]:
    words = normalize_name(name)[:MAX_NAME_CHARACTERS].split()
    return {bytes.fromhex(crypto.scoped_digest("company-directory-prefix-v1", agency_id, company_id, word[:length]))
        for word in words for length in range(2, min(len(word), MAX_PREFIX_CHARACTERS) + 1)}


def search_digests(search: str, agency_id: uuid.UUID, company_id: uuid.UUID,
    crypto: TravellerReuseCrypto,
) -> tuple[bytes, ...]:
    words = tuple(dict.fromkeys(normalize_name(search).split()))
    if len(words) > MAX_QUERY_WORDS or any(not 2 <= len(word) <= MAX_PREFIX_CHARACTERS for word in words):
        raise ValueError("Use up to eight name parts, each between 2 and 32 characters.")
    return tuple(bytes.fromhex(crypto.scoped_digest("company-directory-prefix-v1", agency_id, company_id, word)) for word in words)
