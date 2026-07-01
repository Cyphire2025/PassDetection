"""Regression tests for the Stage 1 passport extraction architecture."""

from __future__ import annotations

import io
import os
import unittest
from typing import Any

from PIL import Image

from app.application.interfaces.passport_extraction import PassportExtractionResult
from app.infrastructure.ocr.gemini_verifier import GeminiPassportVerifier, GeminiVerificationResult
from app.infrastructure.ocr.mrz import TD3MRZParser
from app.infrastructure.ocr.passport_extraction_service import PassportExtractionService
from app.infrastructure.ocr.preprocessing import ImageQualityAssessment, OCRImagePreprocessor
from app.infrastructure.ocr.stage1_extractor import MRZStageResult, TargetedOCRResult
from app.infrastructure.ocr.stage1_extractor import Stage1MRZExtractor


os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")


class OCRImagePreprocessorTests(unittest.TestCase):
    def test_normalize_preserves_small_dimensions_and_emits_rgb_jpeg(self) -> None:
        source = io.BytesIO()
        Image.new("RGBA", (320, 200), (20, 40, 60, 128)).save(source, format="PNG")

        normalized = OCRImagePreprocessor().normalize(source.getvalue())

        with Image.open(io.BytesIO(normalized)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (320, 200))

    def test_normalize_caps_largest_dimension(self) -> None:
        source = io.BytesIO()
        Image.new("RGB", (4400, 2200), "white").save(source, format="JPEG")

        normalized = OCRImagePreprocessor().normalize(source.getvalue())

        with Image.open(io.BytesIO(normalized)) as image:
            self.assertEqual(image.size, (2200, 1100))


class TD3MRZParserTests(unittest.TestCase):
    def test_parse_indian_passport_mrz_from_demo_image(self) -> None:
        text = "\n".join(
            [
                "P<INDVASHISTHA<<SANTOSH<<<<<<<<<<<<<<<<<<",
                "C5604280<5IND7304305F34120422070443683424<78",
            ]
        )

        result = TD3MRZParser().parse(text)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.fields["surname"], "VASHISTHA")
        self.assertEqual(result.fields["given_names"], "SANTOSH")
        self.assertEqual(result.fields["passport_number"], "C5604280")
        self.assertEqual(result.fields["date_of_birth"], "1973-04-30")
        self.assertEqual(result.fields["date_of_expiry"], "2034-12-04")
        self.assertEqual(result.fields["sex"], "F")

    def test_parse_pads_line_one_when_ocr_drops_trailing_fillers(self) -> None:
        text = "\n".join(
            [
                "P<INDVASHISTHA<<SANTOSH<<<<<<<<<<<<<<<<",
                "C5604280<5IND7304305F34120422070443683424<78",
            ]
        )

        result = TD3MRZParser().parse(text)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.fields["surname"], "VASHISTHA")
        self.assertEqual(result.fields["given_names"], "SANTOSH")

    def test_stage1_mrz_normalizes_noisy_indian_line_one_prefix(self) -> None:
        extractor = Stage1MRZExtractor(
            preprocessor=OCRImagePreprocessor(),
            parser=TD3MRZParser(),
            timeout_seconds=1.0,
        )

        sanitized = extractor._sanitize_indian_td3_text(  # noqa: SLF001
            "P<ITNDVASHISTHA<<SANTOSH<<<<<<<<<<<<<<<<<<\n"
            "C5604280<51IND304305F34120422070443683424<78"
        )

        self.assertIsNotNone(sanitized)
        assert sanitized is not None
        self.assertTrue(sanitized.startswith("P<INDVASHISTHA<<SANTOSH"))


class FakePreprocessor:
    def normalize(self, file_content: bytes) -> bytes:
        return file_content

    def assess_quality(self, _image_bytes: bytes) -> ImageQualityAssessment:
        return ImageQualityAssessment(
            score=0.91,
            sharpness=0.9,
            brightness=0.55,
            contrast=0.8,
            width=1200,
            height=800,
        )


class FakeCache:
    async def get(self, _image_bytes: bytes) -> PassportExtractionResult | None:
        return None

    async def set(self, _image_bytes: bytes, _result: PassportExtractionResult) -> None:
        return None

    def fingerprint(self, _image_bytes: bytes) -> dict[str, str]:
        return {
            "image_hash": "test-hash",
            "cache_version": "test-cache",
            "ocr_logic_version": "test-ocr",
            "pipeline_version": "test-pipeline",
            "confidence_version": "test-confidence",
        }


class FakeGeminiVerifier:
    is_available = False

    async def verify(self, **_kwargs: Any) -> GeminiVerificationResult:
        return GeminiVerificationResult(status="disabled")


class PassportExtractionStage1Tests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_mrz_keeps_checksummed_fields_and_verifies_names_with_targeted_ocr(self) -> None:
        class FakeMRZ:
            async def extract(self, _image_bytes: bytes) -> MRZStageResult:
                return MRZStageResult(
                    fields={
                        "surname": "VASHISTHA",
                        "given_names": "SANTOSH",
                        "passport_number": "C5604280",
                        "nationality": "IND",
                        "issuing_country": "IND",
                        "date_of_birth": "1973-04-30",
                        "date_of_expiry": "2034-12-04",
                        "sex": "F",
                        "mrz_line_1": "P<INDVASHISTHA<<SANTOSH<<<<<<<<<<<<<<<<<<",
                        "mrz_line_2": "C5604280<5IND7304305F34120422070443683424<78",
                    },
                    raw_text=(
                        "P<INDVASHISTHA<<SANTOSH<<<<<<<<<<<<<<<<<<\n"
                        "C5604280<5IND7304305F34120422070443683424<78"
                    ),
                    ocr_text="mrz text",
                    warnings=[],
                    duration_ms=11.0,
                )

        class NameTargetedOCR:
            async def extract(self, _image_bytes: bytes, target_fields: set[str]) -> TargetedOCRResult:
                self_test.assertEqual(target_fields, {"surname", "given_names"})
                return TargetedOCRResult(
                    fields={"surname": "VASHISTHA", "given_names": "SANTOSH"},
                    raw_text={"surname": "VASHISTHA", "given_names": "SANTOSH"},
                    duration_ms=4.0,
                )

        self_test = self

        service = PassportExtractionService(
            image_preprocessor=FakePreprocessor(),  # type: ignore[arg-type]
            mrz_extractor=FakeMRZ(),  # type: ignore[arg-type]
            targeted_ocr=NameTargetedOCR(),  # type: ignore[arg-type]
            gemini_verifier=FakeGeminiVerifier(),  # type: ignore[arg-type]
            cache=FakeCache(),  # type: ignore[arg-type]
        )

        result = await service.extract(b"image", filename="passport.jpg", content_type="image/jpeg")

        self.assertEqual(result.extracted_fields["surname"], "VASHISTHA")
        self.assertEqual(result.extracted_fields["passport_number"], "C5604280")
        self.assertEqual(result.extracted_fields["extraction_sources"]["surname"], "targeted_ocr")
        self.assertEqual(result.extracted_fields["field_validation"]["status"], "valid")

    async def test_targeted_ocr_fills_only_missing_mrz_fields(self) -> None:
        requested_targets: set[str] = set()

        class IncompleteMRZ:
            async def extract(self, _image_bytes: bytes) -> MRZStageResult:
                return MRZStageResult(
                    fields={
                        "surname": "VASHISTHA",
                        "passport_number": "C5604280",
                        "nationality": "IND",
                        "issuing_country": "IND",
                        "date_of_birth": "1973-04-30",
                        "date_of_expiry": "2034-12-04",
                        "sex": "F",
                    },
                    raw_text=None,
                    ocr_text="mrz text",
                    warnings=[],
                    duration_ms=9.0,
                )

        class FillingTargetedOCR:
            async def extract(self, _image_bytes: bytes, target_fields: set[str]) -> TargetedOCRResult:
                requested_targets.update(target_fields)
                return TargetedOCRResult(
                    fields={"given_names": "SANTOSH"},
                    raw_text={"given_names": "SANTOSH"},
                    duration_ms=8.0,
                )

        service = PassportExtractionService(
            image_preprocessor=FakePreprocessor(),  # type: ignore[arg-type]
            mrz_extractor=IncompleteMRZ(),  # type: ignore[arg-type]
            targeted_ocr=FillingTargetedOCR(),  # type: ignore[arg-type]
            gemini_verifier=FakeGeminiVerifier(),  # type: ignore[arg-type]
            cache=FakeCache(),  # type: ignore[arg-type]
        )

        result = await service.extract(b"image", filename="passport.jpg", content_type="image/jpeg")

        self.assertEqual(requested_targets, {"surname", "given_names"})
        self.assertEqual(result.extracted_fields["given_names"], "SANTOSH")
        self.assertEqual(result.extracted_fields["extraction_sources"]["given_names"], "targeted_ocr")


class GeminiVerifierTests(unittest.TestCase):
    def test_response_text_supports_gemini_generate_content_shape(self) -> None:
        data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": '{"field_results": {}, "corrections": {}}'},
                        ]
                    }
                }
            ]
        }

        self.assertEqual(
            GeminiPassportVerifier._response_text(data),  # noqa: SLF001
            '{"field_results": {}, "corrections": {}}',
        )


if __name__ == "__main__":
    unittest.main()
