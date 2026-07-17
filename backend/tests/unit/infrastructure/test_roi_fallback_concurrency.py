from __future__ import annotations

import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.infrastructure.ocr.data_page_ocr import (
    DataPageOCRLine,
    DataPageOCRResult,
)
from app.infrastructure.ocr.roi.service import ROIFallbackService


class _CountingReader:
    def __init__(self) -> None:
        self.calls = 0

    def read(self, _image_bytes: bytes, *, timeout_seconds: float) -> DataPageOCRResult:
        self.calls += 1
        self.timeout_seconds = timeout_seconds
        lines = (
            DataPageOCRLine("Surname KHANNA", 0.96),
            DataPageOCRLine("Given Names KHUSHI", 0.95),
            DataPageOCRLine("Passport No C9391041", 0.98),
            DataPageOCRLine("Date of Issue 18 MAR 2025", 0.93),
        )
        return DataPageOCRResult(
            lines=lines,
            text="\n".join(line.text for line in lines),
            confidence=0.95,
            duration_ms=12.0,
            debug={"ocr_invocations": 1},
        )


class ROIFallbackSinglePassTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_requested_fields_reuse_one_visual_ocr_invocation(self) -> None:
        reader = _CountingReader()
        with patch(
            "app.infrastructure.ocr.roi.service.get_settings",
            return_value=SimpleNamespace(roi_field_timeout_seconds=1.0),
        ):
            result = await ROIFallbackService(reader=reader).extract(
                b"normalized-front",
                {"surname", "given_names", "passport_number", "date_of_issue"},
                overall_timeout_seconds=0.8,
            )

        self.assertEqual(reader.calls, 1)
        self.assertEqual(result.debug["ocr_invocations"], 1)
        self.assertEqual(result.fields["surname"], "KHANNA")
        self.assertEqual(result.fields["given_names"], "KHUSHI")
        self.assertEqual(result.fields["passport_number"], "C9391041")
        self.assertEqual(result.fields["date_of_issue"], "2025-03-18")

    async def test_one_visual_read_obeys_the_overall_deadline(self) -> None:
        class _SlowReader:
            calls = 0

            def read(self, _image_bytes: bytes, *, timeout_seconds: float) -> DataPageOCRResult:
                del timeout_seconds
                self.calls += 1
                time.sleep(0.2)
                return DataPageOCRResult((), "", 0.0, 200.0)

        reader = _SlowReader()
        started = time.perf_counter()
        with patch(
            "app.infrastructure.ocr.roi.service.get_settings",
            return_value=SimpleNamespace(roi_field_timeout_seconds=1.0),
        ):
            result = await ROIFallbackService(reader=reader).extract(
                b"normalized-front",
                {"surname", "passport_number"},
                overall_timeout_seconds=0.03,
            )

        self.assertLess(time.perf_counter() - started, 0.12)
        self.assertEqual(reader.calls, 1)
        self.assertEqual(result.fields, {})
        self.assertTrue(result.debug["budget_exhausted"])

        # Let the cancelled test thread finish before the isolated loop closes.
        await asyncio.sleep(0.2)


if __name__ == "__main__":
    unittest.main()
