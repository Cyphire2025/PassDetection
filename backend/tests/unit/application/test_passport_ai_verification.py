"""Application-level safety tests for optional AI passport verification."""

from __future__ import annotations

import unittest

from app.application.interfaces.passport_verification import PassportVerificationResult
from app.application.use_cases.passports.passport_ai_verification import verify_passport_fields


class _BrokenVerifier:
    async def verify(self, *_args, **_kwargs) -> PassportVerificationResult:  # type: ignore[no-untyped-def]
        raise RuntimeError("provider bug")


class _InconsistentVerifier:
    async def verify(self, *_args, **_kwargs) -> PassportVerificationResult:  # type: ignore[no-untyped-def]
        return PassportVerificationResult(
            merged_fields={
                "passport_number": "C9391041",
                "ai_verification": {"status": "verified", "available": True},
            },
            metadata={"status": "provider_unavailable", "available": False},
        )


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

    async def test_authoritative_metadata_overwrites_inconsistent_merged_status(self) -> None:
        result = await verify_passport_fields(
            _InconsistentVerifier(),  # type: ignore[arg-type]
            image_content=b"image",
            content_type="image/jpeg",
            extracted_fields={"passport_number": "C9391041"},
        )

        self.assertEqual(
            result["ai_verification"],
            {"status": "provider_unavailable", "available": False},
        )

if __name__ == "__main__":
    unittest.main()
