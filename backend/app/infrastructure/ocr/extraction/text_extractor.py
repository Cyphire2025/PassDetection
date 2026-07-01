"""Multi-engine plain-text OCR extraction."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from functools import cached_property
from typing import Protocol

from app.application.interfaces.ocr_engine import IOCREngine
from app.core.logging.logger import get_logger
from app.infrastructure.ocr.engines import build_ocr_engine
from app.infrastructure.ocr.preprocessing import OCRImagePreprocessor

logger = get_logger(__name__)


class OCRSelectionSettings(Protocol):
    primary_engine: str
    fallback_engine: str
    fast_mode_enabled: bool
    engine_timeout_seconds: float
    run_deep_ensemble: bool


class OCRTextExtractor:
    """Runs available engines and preprocessing variants, then deduplicates text."""

    def __init__(
        self,
        settings: OCRSelectionSettings,
        *,
        preprocessor: OCRImagePreprocessor | None = None,
        engine_factory: Callable[[str], IOCREngine | None] = build_ocr_engine,
    ) -> None:
        self._settings = settings
        self._preprocessor = preprocessor or OCRImagePreprocessor()
        self._engine_factory = engine_factory

    async def extract_all(self, image_bytes: bytes) -> list[str]:
        if getattr(self._settings, "fast_mode_enabled", True):
            primary_names = self._fast_engine_order(include_fallback=False)
            tasks = [
                self._run_thread_with_timeout(self._extract_engine_texts, image_bytes, primary_names),
                self._run_thread_with_timeout(self._extract_tesseract_variants, image_bytes),
            ]
            texts = await self._collect_texts(tasks)
            if texts or not getattr(self._settings, "run_deep_ensemble", False):
                return self.deduplicate(texts)

            fallback_names = self._fast_engine_order(include_fallback=True)
            fallback_texts = await self._collect_texts(
                [self._run_thread_with_timeout(self._extract_engine_texts, image_bytes, fallback_names)]
            )
            return self.deduplicate(texts + fallback_texts)

        tasks = [
            self._run_thread_with_timeout(self._extract_engine_texts, image_bytes, self.engine_order),
            self._run_thread_with_timeout(self._extract_tesseract_variants, image_bytes),
        ]
        texts = await self._collect_texts(tasks)
        return self.deduplicate(texts)

    async def _collect_texts(self, tasks: list[asyncio.Task | asyncio.Future]) -> list[str]:
        texts: list[str] = []
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, BaseException):
                logger.warning("ocr_ensemble_attempt_failed", error=str(result))
                continue
            texts.extend(result)
        return texts

    async def _run_thread_with_timeout(self, func: Callable, *args) -> list[str]:  # type: ignore[type-arg]
        timeout = getattr(self._settings, "engine_timeout_seconds", 4.0)
        try:
            return await asyncio.wait_for(asyncio.to_thread(func, *args), timeout=timeout)
        except TimeoutError:
            logger.warning("ocr_attempt_timeout", timeout_seconds=timeout)
            return []

    async def extract_first(self, image_bytes: bytes) -> str | None:
        for engine in self.engine_order:
            try:
                normalized = self.normalize(self._run_engine(engine, image_bytes))
            except Exception as exc:
                logger.warning("ocr_engine_attempt_failed", engine=engine, error=str(exc))
                continue
            if normalized:
                return normalized
        return None

    def _extract_engine_texts(self, image_bytes: bytes, engine_names: list[str] | None = None) -> list[str]:
        texts: list[str] = []
        for engine in engine_names or self.engine_order:
            try:
                normalized = self.normalize(self._run_engine(engine, image_bytes))
            except Exception as exc:
                logger.warning("ocr_engine_attempt_failed", engine=engine, error=str(exc))
                continue
            if normalized:
                texts.append(normalized)
        return texts

    def _extract_tesseract_variants(self, image_bytes: bytes) -> list[str]:
        try:
            import pytesseract
        except Exception as exc:
            logger.warning("tesseract_variant_ocr_unavailable", error=str(exc))
            return []

        texts: list[str] = []
        for image, config in self._preprocessor.tesseract_jobs(image_bytes):
            try:
                normalized = self.normalize(pytesseract.image_to_string(image, config=config))
            except Exception as exc:
                logger.warning("tesseract_variant_ocr_failed", error=str(exc))
                continue
            if normalized:
                texts.append(normalized)
        return texts

    def _run_engine(self, engine: str, image_bytes: bytes) -> str | None:
        adapter = self._adapter_for(engine)
        if adapter is None:
            return None
        result = adapter.extract_text(image_bytes)
        return result.text if result else None

    def _fast_engine_order(self, *, include_fallback: bool) -> list[str]:
        configured = [self._settings.primary_engine]
        if include_fallback:
            configured.append(self._settings.fallback_engine)
        configured.append("tesseract")
        return list(dict.fromkeys(configured))

    @cached_property
    def engine_order(self) -> list[str]:
        configured = [
            self._settings.primary_engine,
            self._settings.fallback_engine,
            "tesseract",
            "easyocr",
            "paddleocr",
        ]
        return list(dict.fromkeys(configured))

    @cached_property
    def engines(self) -> dict[str, IOCREngine]:
        return {}

    def _adapter_for(self, name: str) -> IOCREngine | None:
        if name not in self.engines:
            adapter = self._engine_factory(name)
            if adapter is not None:
                self.engines[name] = adapter
        return self.engines.get(name)

    @staticmethod
    def normalize(text: str | None) -> str | None:
        if not text:
            return None
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines[:20]) if lines else None

    @classmethod
    def deduplicate(cls, texts: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for text in texts:
            normalized = cls.normalize(text)
            if not normalized:
                continue
            key = re.sub(r"\s+", "", normalized.upper())
            if key not in seen:
                seen.add(key)
                unique.append(normalized)
        return unique
