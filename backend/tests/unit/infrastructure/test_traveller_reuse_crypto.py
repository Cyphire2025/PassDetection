import uuid

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.core.config.traveller_reuse import TravellerReuseSettings
from app.infrastructure.security.traveller_reuse_crypto import (
    ReuseCryptoUnavailable,
    TravellerReuseCrypto,
)


def test_missing_keys_fail_closed():
    assert TravellerReuseSettings().disclosure_enabled is False
    with pytest.raises(ReuseCryptoUnavailable):
        TravellerReuseCrypto(TravellerReuseSettings())


def test_identifiers_are_tenant_company_and_purpose_scoped():
    crypto = TravellerReuseCrypto(TravellerReuseSettings(
        lookup_key=SecretStr("synthetic-unit-test-key-01234567890123456789"),
        encryption_key=SecretStr(Fernet.generate_key().decode()),
    ))
    agency, company = uuid.uuid4(), uuid.uuid4()
    digest = crypto.passport_fingerprint(agency, company, "000O123", "IND", "P")
    assert digest != crypto.passport_fingerprint(agency, uuid.uuid4(), "000O123", "IND", "P")
    assert digest != crypto.passport_fingerprint(uuid.uuid4(), company, "000O123", "IND", "P")
    assert digest != crypto.passport_fingerprint(agency, company, "0000123", "IND", "P")
    assert crypto.digest("claim", "value") != crypto.digest("grant", "value")
    assert crypto.decrypt(crypto.encrypt("000O123")) == "000O123"
    with pytest.raises(ReuseCryptoUnavailable):
        crypto.decrypt("not-a-ciphertext")
