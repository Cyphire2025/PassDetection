"""Version identifiers for deterministic Indian TD3 passport OCR."""

from __future__ import annotations

INDIAN_TD3_DOCUMENT_PROFILE = {
    "country_code": "IND",
    "document_type": "passport",
    "icao_format": "TD3",
    "scope": "standard_indian_passports_v1",
}

PIPELINE_VERSION = "passport-first-pass-bounded-pipeline-v3-2026-07-17"
OCR_LOGIC_VERSION = "td3-single-plus-data-page-single-v15-2026-07-17"
CONFIDENCE_VERSION = "weighted-signal-v2"
CACHE_VERSION = "ocr-cache-v2"
