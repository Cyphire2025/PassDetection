"""Fast MRZ-strip OCR used before the expensive full-document ensemble."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.core.logging.logger import get_logger
from app.infrastructure.ocr.preprocessing import OCRImagePreprocessor

logger = get_logger(__name__)


@dataclass(frozen=True)
class MRZStripText:
    text: str
    variant: str
    duration_ms: float


class MRZStripExtractor:
    """Runs bounded Tesseract OCR over only the TD3 MRZ region."""

    def __init__(self, preprocessor: OCRImagePreprocessor, *, timeout_seconds: float = 1.6) -> None:
        self._preprocessor = preprocessor
        self._timeout_seconds = timeout_seconds

    async def extract_all(self, image_bytes: bytes) -> list[MRZStripText]:
        try:
            import pytesseract  # noqa: F401
        except Exception as exc:
            logger.warning("mrz_strip_ocr_unavailable", error=str(exc))
            return []

        jobs = await asyncio.to_thread(self._preprocessor.mrz_tesseract_jobs, image_bytes)
        tasks = [self._run_job(image, config, variant) for image, config, variant in jobs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        texts: list[MRZStripText] = []
        seen: set[str] = set()
        for result in results:
            if isinstance(result, BaseException):
                logger.warning("mrz_strip_ocr_failed", error=str(result))
                continue
            normalized_key = "".join(result.text.split()).upper()
            if normalized_key and normalized_key not in seen:
                seen.add(normalized_key)
                texts.append(result)
        return texts

    async def _run_job(self, image, config: str, variant: str) -> MRZStripText:  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(self._image_to_string, image, config),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            logger.warning("mrz_strip_ocr_timeout", variant=variant, timeout_seconds=self._timeout_seconds)
            text = ""
        finally:
            try:
                image.close()
            except Exception:
                pass
        return MRZStripText(
            text=text.strip().upper(),
            variant=variant,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    @staticmethod
    def _image_to_string(image, config: str) -> str:  # type: ignore[no-untyped-def]
        import pytesseract

        return pytesseract.image_to_string(image, config=config)
