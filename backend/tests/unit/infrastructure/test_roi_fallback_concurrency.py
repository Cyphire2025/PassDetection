from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.infrastructure.ocr.roi.base import ROIExtractionResult
from app.infrastructure.ocr.roi.service import ROIFallbackService


class ROIFallbackConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_fields_run_with_bounded_parallelism(self) -> None:
        extractors = [
            SimpleNamespace(field_name=field_name)
            for field_name in ("surname", "given_names", "passport_number", "date_of_expiry")
        ]
        active = 0
        maximum_active = 0

        async def fake_to_thread(function, extractor, image_bytes):  # type: ignore[no-untyped-def]
            nonlocal active, maximum_active
            del function, image_bytes
            active += 1
            maximum_active = max(maximum_active, active)
            try:
                await asyncio.sleep(0.02)
                return ROIExtractionResult(
                    field_name=extractor.field_name,
                    value=f"value-{extractor.field_name}",
                    confidence=0.9,
                    source=f"roi_{extractor.field_name}",
                )
            finally:
                active -= 1

        with (
            patch(
                "app.infrastructure.ocr.roi.service.get_settings",
                return_value=SimpleNamespace(
                    roi_field_timeout_seconds=1.0,
                    roi_max_concurrency=2,
                ),
            ),
            patch(
                "app.infrastructure.ocr.roi.service.asyncio.to_thread",
                new=fake_to_thread,
            ),
        ):
            result = await ROIFallbackService(extractors=extractors).extract(
                b"decoded-in-test",
                {extractor.field_name for extractor in extractors},
            )

        self.assertEqual(maximum_active, 2)
        self.assertEqual(len(result.recovered_fields), 4)
        self.assertEqual(result.attempted_fields, sorted(result.recovered_fields))


if __name__ == "__main__":
    unittest.main()
