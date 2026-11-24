"""Both inbound providers share safe handling of untrusted retry headers."""

import pytest

from app.infrastructure.email.gmail_provider import _retry_after_seconds as gmail_retry
from app.infrastructure.email.outlook_provider import _retry_after_seconds as outlook_retry


@pytest.mark.parametrize("parse", [gmail_retry, outlook_retry])
@pytest.mark.parametrize("value, expected", [
    (None, None), ("", None), ("invalid", None), (" 120 ", 120),
    ("0", 0), ("99999", 86400), ("9" * 5000, 86400),
    ("0" * 5000 + "12", 12), ("²", None),
    ("Wed, 21 Oct 2015 07:28:00 GMT", 0),
])
def test_provider_retry_headers(parse, value, expected):
    assert parse(value) == expected
