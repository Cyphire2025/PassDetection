"""Regression tests for the MRZ-only passport extraction path."""

from __future__ import annotations

import io
import os
import unittest

from PIL import Image, ImageDraw, ImageFont

from app.application.interfaces.passport_extraction import PassportExtractionResult
from app.infrastructure.ocr.correction import ICAOCorrectionEngine
from app.infrastructure.ocr.detection import MRZDetectionFailure, MRZDetectionResult, MRZRegionDetector
from app.infrastructure.ocr.mrz_image_normalizer import MRZImageNormalizer
from app.infrastructure.ocr.mrz import TD3MRZParser
from app.infrastructure.ocr.passport_extraction_service import PassportExtractionService
from app.infrastructure.ocr.preprocessing import ImageQualityAssessment, OCRImagePreprocessor
from app.infrastructure.ocr.roi.service import ROIFallbackResult
from app.infrastructure.ocr.stage1_extractor import MRZStageResult, Stage1MRZExtractor


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

    def test_stage1_uses_lower_page_fallback_when_cv_mrz_detection_is_uncertain(self) -> None:
        class _UnavailableDetector:
            def detect(self, _content: bytes) -> MRZDetectionResult:
                return MRZDetectionResult(
                    crop=None,
                    bbox=None,
                    score=0.0,
                    elapsed_ms=1.0,
                    candidate_count=0,
                    failure=MRZDetectionFailure("no_mrz_candidate"),
                )

        source = io.BytesIO()
        Image.new("RGB", (1000, 700), "white").save(source, format="JPEG")
        extractor = Stage1MRZExtractor(
            preprocessor=OCRImagePreprocessor(),
            parser=TD3MRZParser(),
            timeout_seconds=1.0,
            detector=_UnavailableDetector(),  # type: ignore[arg-type]
        )

        crop = extractor._prepare_mrz_crop(source.getvalue())  # noqa: SLF001

        self.assertEqual(crop.size, (1000, 308))


class MRZRegionDetectorTests(unittest.TestCase):
    def test_detects_shifted_td3_mrz_without_fixed_bottom_crop(self) -> None:
        self._skip_without_cv2()
        image_bytes = self._synthetic_passport(
            mrz_top=330,
            line1="P<INDVASHISTHA<<NIPUN<<<<<<<<<<<<<<<<<<",
            line2="W7114767<5IND0408237M32120802077188321822<58",
        )

        result = MRZRegionDetector().detect(image_bytes)

        self.assertTrue(result.found, result.failure)
        assert result.bbox is not None
        left, top, right, bottom = result.bbox
        self.assertLess(top, 380)
        self.assertGreater(bottom, 390)
        self.assertGreater(right - left, 700)
        self.assertGreaterEqual(result.score, 0.58)

    def test_returns_structured_failure_when_no_mrz_candidate_exists(self) -> None:
        self._skip_without_cv2()
        image = Image.new("RGB", (1000, 700), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 80, 920, 620), outline="black", width=3)
        draw.text((120, 140), "PASSPORT", fill="black", font=self._font(42))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")

        result = MRZRegionDetector().detect(buffer.getvalue())

        self.assertFalse(result.found)
        self.assertIsNotNone(result.failure)
        assert result.failure is not None
        self.assertIn(result.failure.reason, {"no_mrz_candidate", "low_confidence_mrz_candidate"})

    def _synthetic_passport(self, *, mrz_top: int, line1: str, line2: str) -> bytes:
        image = Image.new("RGB", (1200, 760), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((55, 45, 1145, 705), outline=(30, 30, 30), width=4)
        draw.rectangle((90, 110, 360, 430), outline=(80, 80, 80), width=2)
        draw.text((430, 120), "REPUBLIC OF INDIA", fill="black", font=self._font(34))
        draw.text((430, 210), "Surname / Given Names", fill="black", font=self._font(24))
        font = self._font(38)
        draw.text((90, mrz_top), line1, fill="black", font=font)
        draw.text((90, mrz_top + 52), line2, fill="black", font=font)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=92)
        return buffer.getvalue()

    @staticmethod
    def _font(size: int):
        try:
            return ImageFont.truetype("DejaVuSansMono.ttf", size=size)
        except Exception:
            return ImageFont.load_default()

    def _skip_without_cv2(self) -> None:
        try:
            import cv2  # noqa: F401
        except Exception:
            self.skipTest("OpenCV is not installed in this Python environment")


class MRZImageNormalizerTests(unittest.TestCase):
    def test_normalizes_two_mrz_lines_into_single_ocr_image(self) -> None:
        self._skip_without_cv2()
        crop = Image.new("L", (900, 120), "white")
        draw = ImageDraw.Draw(crop)
        font = self._font(28)
        draw.text((8, 18), "P<INDVASHISTHA<<RIDHIMA<<<<<<<<<<<<<<<<<<<<<", fill="black", font=font)
        draw.text((3, 68), "W7095696<0IND1203093F27112762077191069422<64", fill="black", font=font)

        normalized = MRZImageNormalizer().normalize(crop)

        self.assertEqual(normalized.mode, "L")
        self.assertEqual(normalized.info.get("dpi"), (300, 300))
        self.assertGreater(normalized.width, crop.width)
        self.assertGreater(normalized.height, crop.height)

    @staticmethod
    def _font(size: int):
        try:
            return ImageFont.truetype("DejaVuSansMono.ttf", size=size)
        except Exception:
            return ImageFont.load_default()

    def _skip_without_cv2(self) -> None:
        try:
            import cv2  # noqa: F401
        except Exception:
            self.skipTest("OpenCV is not installed in this Python environment")


class ICAOCorrectionEngineTests(unittest.TestCase):
    def test_corrects_td3_line2_with_checksum_and_name_filler_noise(self) -> None:
        raw = "\n".join(
            [
                "P<INDVASHISTHA<<NIPUNK<K<<KK<K<KKKKKKKKKKEKE",
                "W7114767<51ND0408237M32120802077188321822<58",
            ]
        )

        result = ICAOCorrectionEngine().correct(raw)

        self.assertEqual(
            result.corrected_mrz,
            "\n".join(
                [
                    "P<INDVASHISTHA<<NIPUN<<<<<<<<<<<<<<<<<<<<<<<",
                    "W7114767<5IND0408237M32120802077188321822<58",
                ]
            ),
        )
        self.assertEqual(result.checksum_pass_rate, 1.0)
        self.assertLess(result.duration_ms, 20)
        self.assertEqual(result.provenance["nationality"].original_ocr_value, "1ND")
        self.assertEqual(result.provenance["nationality"].corrected_value, "IND")

    def test_recovers_ocr_confused_name_separator_without_checksum_guessing(self) -> None:
        raw = "\n".join(
            [
                "P<INDVASHISTHACERIDHIMASSSKKKK<KKKKKKKKK<<<<<",
                "W7095696<01ND1203093F27112762077191069422<64",
            ]
        )

        result = ICAOCorrectionEngine().correct(raw)

        self.assertEqual(result.line1, "P<INDVASHISTHA<<RIDHIMA<<<<<<<<<<<<<<<<<<<<<")
        self.assertEqual(result.provenance["given_names"].corrected_value, "RIDHIMA")
        self.assertEqual(result.provenance["passport_number"].checksum_status, "pass")

    def test_recovers_single_td3_name_separator(self) -> None:
        raw = "\n".join(
            [
                "P<INDKHANNA<KHUSHI<<<<<<<<<<<<<<<<<<<<<<<",
                "C9391041<1IND0412155F3503188F060819601425<32",
            ]
        )

        result = ICAOCorrectionEngine().correct(raw)

        self.assertEqual(result.provenance["surname"].corrected_value, "KHANNA")
        self.assertEqual(result.provenance["given_names"].corrected_value, "KHUSHI")
        self.assertEqual(result.line1, "P<INDKHANNA<<KHUSHI<<<<<<<<<<<<<<<<<<<<<<<<<")

    def test_recovers_x_confused_td3_name_separator(self) -> None:
        raw = "\n".join(
            [
                "P<INDKHANNAXKHUSHI<<<<<<<<<<<<<<<<<<<<<<",
                "C9391041<1IND0412155F3503188F060819601425<32",
            ]
        )

        result = ICAOCorrectionEngine().correct(raw)

        self.assertEqual(result.provenance["surname"].corrected_value, "KHANNA")
        self.assertEqual(result.provenance["given_names"].corrected_value, "KHUSHI")
        self.assertEqual(result.line1, "P<INDKHANNA<<KHUSHI<<<<<<<<<<<<<<<<<<<<<<<<<")

    def test_missing_leading_passport_character_stays_review_when_checksum_ambiguous(self) -> None:
        raw = "\n".join(
            [
                "P<INDKHANNA<<KHUSHI<<<<<<<<<<<<<<<<<<<<<<",
                "9391041<1IND0412155F3503188F060819601425<32",
            ]
        )

        result = ICAOCorrectionEngine().correct(raw)

        self.assertIn("review_required:passport_number:ambiguous_line2_repair", result.warnings)
        self.assertEqual(result.provenance["passport_number"].checksum_status, "review_required")


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


class FakeROIFallback:
    def __init__(self, fields: dict[str, str]) -> None:
        self._fields = fields
        self.requested_fields: set[str] = set()

    async def extract(self, _image_bytes: bytes, requested_fields: set[str]) -> ROIFallbackResult:
        self.requested_fields = set(requested_fields)
        recovered = {field: value for field, value in self._fields.items() if field in requested_fields}
        return ROIFallbackResult(
            fields=recovered,
            provenance={
                field: {
                    "original_ocr_value": value,
                    "corrected_value": value,
                    "correction_reason": "validated_roi_ocr",
                    "checksum_status": "not_applicable",
                    "confidence": 0.9,
                    "source": "roi_passport_number",
                }
                for field, value in recovered.items()
            },
            attempted_fields=sorted(requested_fields),
            recovered_fields=sorted(recovered),
            duration_ms=3.0,
        )


class PassportExtractionMRZOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_mrz_returns_only_mrz_sources(self) -> None:
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

        service = PassportExtractionService(
            image_preprocessor=FakePreprocessor(),  # type: ignore[arg-type]
            mrz_extractor=FakeMRZ(),  # type: ignore[arg-type]
            cache=FakeCache(),  # type: ignore[arg-type]
        )

        result = await service.extract(b"image", filename="passport.jpg", content_type="image/jpeg")

        self.assertEqual(result.extracted_fields["surname"], "VASHISTHA")
        self.assertEqual(result.extracted_fields["passport_number"], "C5604280")
        self.assertEqual(result.extracted_fields["extraction_sources"]["surname"], "mrz")
        self.assertNotIn("targeted_ocr_text", result.extracted_fields)
        self.assertNotIn("gemini_verification", result.extracted_fields)
        self.assertEqual(result.confidence_score["pipeline"]["name"], "mrz_only")

    async def test_missing_mrz_fields_are_left_empty(self) -> None:
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

        service = PassportExtractionService(
            image_preprocessor=FakePreprocessor(),  # type: ignore[arg-type]
            mrz_extractor=IncompleteMRZ(),  # type: ignore[arg-type]
            cache=FakeCache(),  # type: ignore[arg-type]
        )

        result = await service.extract(b"image", filename="passport.jpg", content_type="image/jpeg")

        self.assertNotIn("given_names", result.extracted_fields)
        self.assertEqual(result.extracted_fields["extraction_sources"]["surname"], "mrz")

    async def test_roi_fills_only_missing_passport_number(self) -> None:
        class MissingPassportNumberMRZ:
            async def extract(self, _image_bytes: bytes) -> MRZStageResult:
                return MRZStageResult(
                    fields={
                        "surname": "KHANNA",
                        "given_names": "KHUSHI",
                        "nationality": "IND",
                        "issuing_country": "IND",
                        "date_of_birth": "2004-12-15",
                        "date_of_expiry": "2035-03-18",
                        "sex": "F",
                    },
                    raw_text=None,
                    ocr_text="mrz text",
                    warnings=[],
                    duration_ms=9.0,
                )

        roi = FakeROIFallback({"passport_number": "C9391041"})
        service = PassportExtractionService(
            image_preprocessor=FakePreprocessor(),  # type: ignore[arg-type]
            mrz_extractor=MissingPassportNumberMRZ(),  # type: ignore[arg-type]
            roi_fallback=roi,  # type: ignore[arg-type]
            cache=FakeCache(),  # type: ignore[arg-type]
        )

        result = await service.extract(b"image", filename="passport.jpg", content_type="image/jpeg")

        self.assertIn("passport_number", roi.requested_fields)
        self.assertEqual(result.extracted_fields["passport_number"], "C9391041")
        self.assertEqual(result.extracted_fields["surname"], "KHANNA")
        self.assertEqual(result.extracted_fields["extraction_sources"]["passport_number"], "roi_passport_number")

    async def test_roi_does_not_run_for_valid_mrz_passport_number(self) -> None:
        class ValidPassportNumberMRZ:
            async def extract(self, _image_bytes: bytes) -> MRZStageResult:
                return MRZStageResult(
                    fields={
                        "surname": "KHANNA",
                        "given_names": "KHUSHI",
                        "passport_number": "C9391041",
                        "nationality": "IND",
                        "issuing_country": "IND",
                        "date_of_birth": "2004-12-15",
                        "date_of_expiry": "2035-03-18",
                        "sex": "F",
                    },
                    raw_text=None,
                    ocr_text="mrz text",
                    warnings=[],
                    duration_ms=9.0,
                )

        roi = FakeROIFallback({"passport_number": "X0000000"})
        service = PassportExtractionService(
            image_preprocessor=FakePreprocessor(),  # type: ignore[arg-type]
            mrz_extractor=ValidPassportNumberMRZ(),  # type: ignore[arg-type]
            roi_fallback=roi,  # type: ignore[arg-type]
            cache=FakeCache(),  # type: ignore[arg-type]
        )

        result = await service.extract(b"image", filename="passport.jpg", content_type="image/jpeg")

        self.assertNotIn("passport_number", roi.requested_fields)
        self.assertEqual(result.extracted_fields["passport_number"], "C9391041")
        self.assertEqual(result.extracted_fields["extraction_sources"]["passport_number"], "mrz")


if __name__ == "__main__":
    unittest.main()
