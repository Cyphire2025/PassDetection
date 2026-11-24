"""Encrypted private export pages reject oversized streams and malformed rows."""

import json

import pytest
from cryptography.fernet import Fernet

from app.core.config.traveller_reuse import TravellerReuseSettings
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto
from app.infrastructure.travellers.company_export_render import (
    MAX_CHUNK_BYTES,
    encode_rows,
    read_rows,
)


@pytest.fixture
def crypto():
    return TravellerReuseCrypto(
        TravellerReuseSettings(
            lookup_key="synthetic-export-lookups-" * 3,
            encryption_key=Fernet.generate_key().decode(),
        )
    )


class StreamStorage:
    def __init__(self, content):
        self.content = content
        self.reads = 0

    async def stream_file(self, _key, **_kwargs):
        self.reads += 1
        midpoint = max(1, len(self.content) // 2)
        yield self.content[:midpoint]
        yield self.content[midpoint:]


@pytest.mark.parametrize("size", [0, MAX_CHUNK_BYTES + 1])
async def test_declared_page_byte_bounds_reject_before_private_storage_read(crypto, size):
    storage = StreamStorage(b"not read")
    with pytest.raises(ValueError, match="export_page_byte_limit"):
        await read_rows(storage, "synthetic-owned-page", size, crypto)
    assert storage.reads == 0


@pytest.mark.parametrize("difference", [-1, 1])
async def test_actual_stream_size_must_match_owned_receipt_before_decryption(crypto, difference):
    content = encode_rows([["synthetic"] * 18], crypto)
    storage = StreamStorage(content)
    with pytest.raises(ValueError, match="export_page_size_changed"):
        await read_rows(storage, "synthetic-owned-page", len(content) + difference, crypto)
    assert storage.reads == 1


@pytest.mark.parametrize(
    "rows",
    [
        {"unexpected": "object"},
        [[]] * 251,
        ["not a row"],
        [["short"]],
        [[""] * 17 + [{"unexpected": "cell object"}]],
    ],
)
async def test_decrypted_pages_keep_row_count_width_and_scalar_contract(crypto, rows):
    content = crypto.encrypt(json.dumps(rows)).encode()
    storage = StreamStorage(content)
    with pytest.raises(ValueError, match="export_page_shape"):
        await read_rows(storage, "synthetic-owned-page", len(content), crypto)


def test_oversized_encrypted_output_cannot_become_an_owned_page(crypto):
    with pytest.raises(ValueError, match="export_page_byte_limit"):
        encode_rows([["x" * MAX_CHUNK_BYTES]], crypto)
