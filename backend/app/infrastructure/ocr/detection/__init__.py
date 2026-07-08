"""Deterministic MRZ region detection."""

from app.infrastructure.ocr.detection.mrz_detector import (
    MRZDetectionFailure,
    MRZDetectionResult,
    MRZRegionDetector,
)

__all__ = ["MRZDetectionFailure", "MRZDetectionResult", "MRZRegionDetector"]
