"""Short-lived OCR result cache keyed by image hash."""

from __future__ import annotations

import hashlib
import importlib
import json
import time
from typing import Any

from app.application.interfaces.passport_extraction import PassportExtractionResult
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.infrastructure.ocr.versioning import (
    CACHE_VERSION,
    CONFIDENCE_VERSION,
    OCR_LOGIC_VERSION,
    PIPELINE_VERSION,
)


def _load_async_redis() -> Any:
    try:
        module = importlib.import_module("redis.asyncio")
    except Exception:  # pragma: no cover - optional runtime dependency
        return None
    return getattr(module, "Redis", None)


_AsyncRedis: Any = _load_async_redis()

logger = get_logger(__name__)


class ExtractionCache:
    _local_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def __init__(self) -> None:
        self._settings = get_settings()
        self._redis: Any | None = None
        if self._settings.ocr_cache_ttl_seconds > 0 and _AsyncRedis is not None:
            try:
                self._redis = _AsyncRedis.from_url(
                    self._settings.redis.cache_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
            except Exception as exc:
                logger.warning(
                    "ocr_cache_redis_init_failed",
                    error_type=type(exc).__name__,
                )

    async def get(self, image_bytes: bytes) -> PassportExtractionResult | None:
        ttl = self._settings.ocr_cache_ttl_seconds
        if ttl <= 0:
            return None
        key = self._key(image_bytes)

        payload: str | None = None
        if self._redis is not None:
            try:
                payload = await self._redis.get(key)
            except Exception as exc:
                logger.warning(
                    "ocr_cache_redis_get_failed",
                    error_type=type(exc).__name__,
                )
                self._redis = None

        if payload is None:
            cached = self._local_cache.get(key)
            if cached and cached[0] > time.time():
                return self._from_payload(cached[1], cache_key=key)
            return None

        try:
            return self._from_payload(json.loads(payload), cache_key=key)
        except Exception as exc:
            logger.warning(
                "ocr_cache_decode_failed",
                error_type=type(exc).__name__,
            )
            return None

    async def set(self, image_bytes: bytes, result: PassportExtractionResult) -> None:
        ttl = self._settings.ocr_cache_ttl_seconds
        if ttl <= 0:
            return
        key = self._key(image_bytes)
        payload = {
            "extracted_fields": result.extracted_fields,
            "overall_confidence": result.overall_confidence,
            "confidence_score": result.confidence_score,
            "mrz_raw": result.mrz_raw,
            "cache_version": CACHE_VERSION,
            "ocr_logic_version": OCR_LOGIC_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "confidence_version": CONFIDENCE_VERSION,
        }
        self._local_cache[key] = (time.time() + ttl, payload)
        if self._redis is not None:
            try:
                await self._redis.setex(key, ttl, json.dumps(payload, default=str))
            except Exception as exc:
                logger.warning(
                    "ocr_cache_redis_set_failed",
                    error_type=type(exc).__name__,
                )
                self._redis = None

    def _from_payload(
        self,
        payload: dict[str, Any],
        *,
        cache_key: str,
    ) -> PassportExtractionResult:
        score = dict(payload.get("confidence_score") or {})
        score["cache"] = {
            "hit": True,
            "image_hash": cache_key.rsplit(":", 1)[-1][:12],
            "cache_version": payload.get("cache_version") or CACHE_VERSION,
            "ocr_logic_version": payload.get("ocr_logic_version") or OCR_LOGIC_VERSION,
            "pipeline_version": payload.get("pipeline_version") or PIPELINE_VERSION,
            "confidence_version": payload.get("confidence_version") or CONFIDENCE_VERSION,
        }
        return PassportExtractionResult(
            extracted_fields=payload.get("extracted_fields") or {},
            overall_confidence=float(payload.get("overall_confidence") or 0.0),
            confidence_score=score,
            mrz_raw=payload.get("mrz_raw"),
        )

    def fingerprint(self, image_bytes: bytes) -> dict[str, str]:
        return {
            "image_hash": self._digest(image_bytes)[:12],
            "cache_version": CACHE_VERSION,
            "ocr_logic_version": OCR_LOGIC_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "confidence_version": CONFIDENCE_VERSION,
        }

    def _key(self, image_bytes: bytes) -> str:
        digest = self._digest(image_bytes)
        return (
            f"ocr-result:{CACHE_VERSION}:{PIPELINE_VERSION}:"
            f"{OCR_LOGIC_VERSION}:{CONFIDENCE_VERSION}:{digest}"
        )

    @staticmethod
    def _digest(image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()
