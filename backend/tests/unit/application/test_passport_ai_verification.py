"""Application-level safety tests for optional AI passport verification."""

from __future__ import annotations

import unittest

from app.application.interfaces.passport_verification import PassportVerificationResult
from app.application.use_cases.passports.passport_ai_verification import verify_passport_fields
from app.application.use_cases.passports.retry_public_passport_extraction_use_case import (
    RetryPublicPassportExtractionUseCase,
)


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

    async def test_retry_accepts_only_explicit_ai_corrections_and_missing_values(self) -> None:
        merged = RetryPublicPassportExtractionUseCase._merge_missing_fields(  # noqa: SLF001
            current={
                "surname": "KHANNA",
                "given_names": "USER EDIT",
                "passport_number": "C9391047",
            },
            refreshed={
                "surname": "SHARMA",
                "given_names": "KHUSHI",
                "passport_number": "C9391041",
                "nationality": "IND",
                "ai_verification": {
                    "corrected_fields": ["passport_number"],
                    "filled_fields": ["nationality"],
                },
            },
        )

        self.assertEqual(merged["surname"], "KHANNA")
        self.assertEqual(merged["given_names"], "USER EDIT")
        self.assertEqual(merged["passport_number"], "C9391041")
        self.assertEqual(merged["nationality"], "IND")


if __name__ == "__main__":
    unittest.main()
