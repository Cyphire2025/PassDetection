from __future__ import annotations

import unittest
from typing import Any

from app.application.interfaces.passport_extraction import PassportExtractionResult
from app.infrastructure.ocr.orchestration import ExtractionPipeline, LocalExtractionResult
from app.infrastructure.ocr.preprocessing import ImageQualityAssessment


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


class FakeValidation:
    status = "valid"
    issues: list[Any] = []


class FakeScore:
    overall = 0.94

    def to_dict(self) -> dict[str, Any]:
        return {"overall": self.overall, "signals": []}


class FakeScorer:
    def score(self, **_kwargs: Any) -> FakeScore:
        return FakeScore()


class FakeValidator:
    def validate(self, _fields: dict[str, str], **_kwargs: Any) -> FakeValidation:
        return FakeValidation()


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


class ExtractionPipelineDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_attaches_stage_diagnostics_without_changing_contract(self) -> None:
        async def extract_local(image_bytes: bytes, filename: str, **kwargs: Any) -> LocalExtractionResult:
            diagnostics = kwargs.get("diagnostics")
            if diagnostics is not None:
                with diagnostics.stage("fake_mrz_ocr", engine="fake"):
                    pass
            return LocalExtractionResult(
                fields={
                    "surname": "DOE",
                    "given_names": "JANE",
                    "passport_number": "A1234567",
                },
                mrz_raw="P<INDDOE<<JANE",
                warnings=[],
                ocr_text=None,
                evidence={"passport_number": {"confidence": 0.95}},
                engines_used=("fake",),
            )

        pipeline = ExtractionPipeline(
            preprocessor=FakePreprocessor(),
            extract_local=extract_local,
            validator=FakeValidator(),
            scorer=FakeScorer(),
            should_use_fallback=lambda _validation, _confidence: False,
            extract_fallback=lambda *_args, **_kwargs: {},
            merge_fallback=lambda local_fields, _fallback_fields: local_fields,
            merge_fields=lambda fields, _ocr_text, _validation: fields,
            cache=FakeCache(),
        )

        result = await pipeline.extract(b"image", filename="passport.jpg", content_type="image/jpeg")

        self.assertEqual(result.overall_confidence, 0.94)
        diagnostics = result.confidence_score["diagnostics"]
        stage_names = [stage["name"] for stage in diagnostics["stages"]]
        self.assertIn("cache_lookup", stage_names)
        self.assertIn("image_normalization", stage_names)
        self.assertIn("image_quality_assessment", stage_names)
        self.assertIn("fake_mrz_ocr", stage_names)
        self.assertIn("field_validation", stage_names)
        self.assertIn("confidence_scoring_final", stage_names)
        self.assertFalse(diagnostics["cache"]["hit"])
        self.assertEqual(diagnostics["document_profile"]["country_code"], "IND")
        self.assertEqual(result.confidence_score["adaptive_pipeline"]["processing_budget"]["total_ms"], 5000.0)

    async def test_pipeline_runs_single_local_pass_for_valid_complete_local_result(self) -> None:
        class LowQualityPreprocessor(FakePreprocessor):
            def assess_quality(self, _image_bytes: bytes) -> ImageQualityAssessment:
                return ImageQualityAssessment(
                    score=0.49,
                    sharpness=0.2,
                    brightness=0.45,
                    contrast=0.4,
                    width=1200,
                    height=800,
                )

        class MediumScore:
            overall = 0.76

            def to_dict(self) -> dict[str, Any]:
                return {"overall": self.overall, "signals": []}

        class MediumScorer:
            def score(self, **_kwargs: Any) -> MediumScore:
                return MediumScore()

        local_calls = 0

        async def extract_local(_image_bytes: bytes, _filename: str, **_kwargs: Any) -> LocalExtractionResult:
            nonlocal local_calls
            local_calls += 1
            return LocalExtractionResult(
                fields={
                    "surname": "VASHISTHA",
                    "given_names": "SANTOSH",
                    "passport_number": "C5604280",
                    "nationality": "IND",
                    "issuing_country": "IND",
                    "date_of_birth": "1973-04-30",
                    "date_of_expiry": "2034-12-04",
                    "sex": "F",
                },
                mrz_raw=None,
                warnings=[],
                ocr_text=None,
                evidence={},
                engines_used=("relaxed_mrz", "visual_text"),
            )

        pipeline = ExtractionPipeline(
            preprocessor=LowQualityPreprocessor(),
            extract_local=extract_local,
            validator=FakeValidator(),
            scorer=MediumScorer(),
            should_use_fallback=lambda _validation, _confidence: False,
            extract_fallback=lambda *_args, **_kwargs: {},
            merge_fallback=lambda local_fields, _fallback_fields: local_fields,
            merge_fields=lambda fields, _ocr_text, _validation: fields,
            cache=FakeCache(),
        )

        result = await pipeline.extract(b"image", filename="passport.jpg", content_type="image/jpeg")

        self.assertEqual(local_calls, 1)
        self.assertNotIn("enhanced_retry_used", result.confidence_score["adaptive_pipeline"])
        self.assertNotIn("enhanced_retry_considered", result.confidence_score["adaptive_pipeline"])


if __name__ == "__main__":
    unittest.main()
