"""Application-level safety tests for optional AI passport verification."""

from __future__ import annotations

import unittest

from app.application.interfaces.passport_verification import PassportVerificationResult
from app.application.use_cases.passports.passport_ai_verification import verify_passport_fields


class _BrokenVerifier:
    async def verify(self, *_args, **_kwargs) -> PassportVerificationResult:  # type: ignore[no-untyped-def]
        raise RuntimeError("provider bug")


class PassportAIVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unexpected_verifier_error_keeps_ocr_fields_reviewable(self) -> None:
        result = await verify_passport_fields(
            _BrokenVerifier(),  # type: ignore[arg-type]
            image_content=b"image",
            content_type="image/jpeg",
            extracted_fields={"passport_number": "C9391041"},
        )

        self.assertEqual(result["passport_number"], "C9391041")
        self.assertEqual(result["ai_verification"]["status"], "internal_error")

if __name__ == "__main__":
    unittest.main()
