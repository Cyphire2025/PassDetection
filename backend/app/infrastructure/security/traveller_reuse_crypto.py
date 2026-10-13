"""Tenant-scoped keyed lookups and encrypted retained identity values.

No unsalted passport/contact hashes; no key fallback to a development secret.
Key rotation requires an explicit bounded reindex/re-encryption job before the
active key version changes. Disabled/unconfigured retrieval always fails closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid

from cryptography.fernet import Fernet, InvalidToken

from app.core.config.traveller_reuse import TravellerReuseSettings
from app.domain.services.traveller_verification import exact_passport_number, issuing_context


class ReuseCryptoUnavailable(RuntimeError):
    pass


class TravellerReuseCrypto:
    def __init__(self, settings: TravellerReuseSettings) -> None:
        if settings.lookup_key is None or settings.encryption_key is None:
            raise ReuseCryptoUnavailable("Traveller reuse keys are not configured")
        key = settings.lookup_key.get_secret_value().encode("utf-8")
        if len(key) < 32 or not 1 <= len(settings.key_version) <= 32:
            raise ReuseCryptoUnavailable("Traveller reuse key configuration is invalid")
        try:
            self._cipher = Fernet(settings.encryption_key.get_secret_value().encode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise ReuseCryptoUnavailable("Traveller reuse encryption key is invalid") from exc
        self._key = key
        self.key_version = settings.key_version

    def digest(self, purpose: str, *values: str) -> str:
        payload = json.dumps(
            ["traveller-reuse", self.key_version, purpose, *values],
            ensure_ascii=True, separators=(",", ":"),
        )
        return hmac.new(self._key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def scoped_digest(
        self, purpose: str, agency_id: uuid.UUID, company_id: uuid.UUID, *values: str,
    ) -> str:
        return self.digest(purpose, str(agency_id), str(company_id), *values)

    def passport_fingerprint(
        self, agency_id: uuid.UUID, company_id: uuid.UUID,
        number: str, issuer: str, document_type: str,
    ) -> str:
        country, kind = issuing_context(issuer, document_type)
        return self.scoped_digest(
            "passport", agency_id, company_id, country, kind, exact_passport_number(number),
        )

    def encrypt(self, value: str) -> str:
        return f"{self.key_version}:{self._cipher.encrypt(value.encode('utf-8')).decode('ascii')}"

    def decrypt(self, value: str) -> str:
        try:
            version, token = value.split(":", 1)
            if version != self.key_version:
                raise ReuseCryptoUnavailable("Retained information key version is unavailable")
            return self._cipher.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeError) as exc:
            raise ReuseCryptoUnavailable("Retained information is unavailable") from exc

    def new_secret(self, purpose: str) -> tuple[str, str]:
        secret = secrets.token_urlsafe(32)
        return secret, self.digest(purpose, secret)
