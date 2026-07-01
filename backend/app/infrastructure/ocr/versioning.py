"""Version identifiers for deterministic Indian TD3 passport OCR."""

from __future__ import annotations

INDIAN_TD3_DOCUMENT_PROFILE = {
    "country_code": "IND",
    "document_type": "passport",
    "icao_format": "TD3",
    "scope": "standard_indian_passports_v1",
}

PIPELINE_VERSION = "indian-td3-stage1-pipeline-2026-07-01"
OCR_LOGIC_VERSION = "indian-td3-stage1-ocr-2026-07-01"
CONFIDENCE_VERSION = "weighted-signal-v2"
CACHE_VERSION = "ocr-cache-v2"
