"""Top-right visual passport-number ROI extractor."""

from __future__ import annotations

import re

from PIL import Image, ImageOps

from app.infrastructure.ocr.roi.base import ROIExtractionResult
from app.infrastructure.ocr.roi.common import ROIImageTools


class PassportNumberROIExtractor:
    field_name = "passport_number"
    source = "roi_passport_number"

    # Search broadly in the upper-right data-page band, then locate the bold
    # visual passport number dynamically inside that band before OCR.
    _search_roi = (0.52, 0.00, 1.00, 0.24)
    _fallback_roi = (0.70, 0.02, 0.99, 0.16)
    _fallback_right_zone_start = 0.25
    _pattern = re.compile(r"\b[A-Z][0-9]{7}\b")

    def extract(self, image: Image.Image) -> ROIExtractionResult | None:
        search_crop = ROIImageTools.relative_crop(image, self._search_roi)
        crop, locator_debug = self._locate_number_crop(search_crop)
        prepared = ROIImageTools.preprocess_text_roi(crop, target_height=180)
        ocr = ROIImageTools.ocr_single_line(prepared, whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", psm=6)
        value = self._select_passport_number(ocr.text)
        if value is None:
            return None
        return ROIExtractionResult(
            field_name=self.field_name,
            value=value,
            confidence=max(0.65, ocr.confidence),
            source=self.source,
            debug={
                "raw_text": ocr.text,
                "ocr_ms": ocr.duration_ms,
                "search_roi": self._search_roi,
                "pattern": "indian_passport_letter_7_digits",
                **locator_debug,
            },
        )

    def _locate_number_crop(self, search_crop: Image.Image) -> tuple[Image.Image, dict[str, object]]:
        try:
            import cv2
            import numpy as np
        except Exception:
            return self._fallback_crop(search_crop), {"locator": "fallback_no_opencv"}

        gray = ImageOps.autocontrast(ImageOps.grayscale(search_crop))
        array = np.asarray(gray, dtype=np.uint8)
        threshold = cv2.threshold(
            cv2.GaussianBlur(array, (3, 3), 0),
            0,
            255,
            cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
        )[1]
        contours, _ = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes: list[tuple[int, int, int, int]] = []
        crop_width, crop_height = gray.size
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if not self._is_character_like(x, y, width, height, crop_width, crop_height):
                continue
            boxes.append((x, y, width, height))

        bands = self._group_line_bands(boxes)
        candidates = [self._score_band(band, crop_width, crop_height) for band in bands]
        candidates = [candidate for candidate in candidates if candidate is not None]
        if not candidates:
            return self._fallback_crop(search_crop), {
                "locator": "fallback_no_candidate",
                "component_count": len(boxes),
            }

        best = max(candidates, key=lambda item: item["score"])
        if best["score"] < 0.50:
            return self._fallback_crop(search_crop), {
                "locator": "fallback_low_score",
                "component_count": len(boxes),
                "best_score": round(float(best["score"]), 3),
            }

        left, top, right, bottom = best["bbox"]
        pad_x = max(8, int((bottom - top) * 0.45))
        pad_y = max(4, int((bottom - top) * 0.45))
        bbox = (
            max(0, left - pad_x),
            max(0, top - pad_y),
            min(crop_width, right + pad_x),
            min(crop_height, bottom + pad_y),
        )
        image_bbox = self._to_image_relative_bbox(bbox, crop_width, crop_height)
        return gray.crop(bbox), {
            "locator": "dynamic_cv",
            "component_count": len(boxes),
            "line_candidate_count": len(candidates),
            "number_bbox": bbox,
            "image_relative_bbox": image_bbox,
            "number_score": round(float(best["score"]), 3),
        }

    def _fallback_crop(self, search_crop: Image.Image) -> Image.Image:
        left = round(search_crop.width * ((self._fallback_roi[0] - self._search_roi[0]) / (self._search_roi[2] - self._search_roi[0])))
        top = round(search_crop.height * ((self._fallback_roi[1] - self._search_roi[1]) / (self._search_roi[3] - self._search_roi[1])))
        right = round(search_crop.width * ((self._fallback_roi[2] - self._search_roi[0]) / (self._search_roi[2] - self._search_roi[0])))
        bottom = round(search_crop.height * ((self._fallback_roi[3] - self._search_roi[1]) / (self._search_roi[3] - self._search_roi[1])))
        fallback = search_crop.crop((left, top, max(left + 1, right), max(top + 1, bottom)))
        number_left = round(fallback.width * self._fallback_right_zone_start)
        return fallback.crop((number_left, 0, fallback.width, fallback.height))

    def _to_image_relative_bbox(
        self,
        search_bbox: tuple[int, int, int, int],
        crop_width: int,
        crop_height: int,
    ) -> tuple[float, float, float, float]:
        search_left, search_top, search_right, search_bottom = self._search_roi
        search_width = search_right - search_left
        search_height = search_bottom - search_top
        left = search_left + (search_bbox[0] / max(1, crop_width)) * search_width
        top = search_top + (search_bbox[1] / max(1, crop_height)) * search_height
        right = search_left + (search_bbox[2] / max(1, crop_width)) * search_width
        bottom = search_top + (search_bbox[3] / max(1, crop_height)) * search_height
        return (
            round(max(0.0, min(1.0, left)), 4),
            round(max(0.0, min(1.0, top)), 4),
            round(max(0.0, min(1.0, right)), 4),
            round(max(0.0, min(1.0, bottom)), 4),
        )

    @staticmethod
    def _is_character_like(x: int, y: int, width: int, height: int, crop_width: int, crop_height: int) -> bool:
        if x < crop_width * 0.28:
            return False
        if y > crop_height * 0.78:
            return False
        if not (3 <= width <= crop_width * 0.16 and 5 <= height <= crop_height * 0.52):
            return False
        aspect = width / max(height, 1)
        return 0.12 <= aspect <= 1.35

    @staticmethod
    def _group_line_bands(boxes: list[tuple[int, int, int, int]]) -> list[list[tuple[int, int, int, int]]]:
        bands: list[list[tuple[int, int, int, int]]] = []
        for box in sorted(boxes, key=lambda item: item[1] + item[3] / 2):
            _, y, _, height = box
            center = y + height / 2
            for band in bands:
                band_center = sum(item[1] + item[3] / 2 for item in band) / len(band)
                avg_height = sum(item[3] for item in band) / len(band)
                if abs(center - band_center) <= max(6, avg_height * 0.75):
                    band.append(box)
                    break
            else:
                bands.append([box])
        return bands

    @staticmethod
    def _score_band(band: list[tuple[int, int, int, int]], crop_width: int, crop_height: int) -> dict[str, object] | None:
        if len(band) < 5:
            return None
        left = min(x for x, _, _, _ in band)
        top = min(y for _, y, _, _ in band)
        right = max(x + width for x, _, width, _ in band)
        bottom = max(y + height for _, y, _, height in band)
        width = right - left
        height = bottom - top
        aspect = width / max(height, 1)
        x_center = (left + right) / 2 / max(crop_width, 1)
        y_center = (top + bottom) / 2 / max(crop_height, 1)
        component_score = max(0.0, 1.0 - abs(len(band) - 8) / 8)
        aspect_score = 1.0 if 3.0 <= aspect <= 12.0 else max(0.0, 1.0 - min(abs(aspect - 6.0), 6.0) / 6.0)
        right_score = min(1.0, max(0.0, (x_center - 0.45) / 0.45))
        top_score = 1.0 - min(1.0, max(0.0, y_center - 0.58) / 0.42)
        score = 0.35 * component_score + 0.30 * aspect_score + 0.25 * right_score + 0.10 * top_score
        return {"bbox": (left, top, right, bottom), "score": score}

    def _select_passport_number(self, text: str) -> str | None:
        compact = re.sub(r"[^A-Z0-9]", "", text.upper())
        matches = self._pattern.findall(compact)
        if not matches:
            return None
        # Prefer the rightmost strict passport-shaped token in the top-right ROI.
        return matches[-1]
