from __future__ import annotations

import os
import unittest

os.environ.setdefault("APP_SECRET_KEY", "unit-test-secret")

try:
    import jose  # noqa: F401

    HAS_JOSE = True
except ModuleNotFoundError:
    HAS_JOSE = False


@unittest.skipUnless(HAS_JOSE, "python-jose is not installed in this Python environment")
class RefreshTokenHashingTests(unittest.TestCase):
    def test_hash_refresh_token_is_deterministic_and_non_plaintext(self) -> None:
        from app.core.security.jwt import hash_refresh_token

        token = "refresh-token-value"

        first = hash_refresh_token(token)
        second = hash_refresh_token(token)

        self.assertEqual(first, second)
        self.assertNotEqual(first, token)
        self.assertEqual(len(first), 64)


if __name__ == "__main__":
    unittest.main()
