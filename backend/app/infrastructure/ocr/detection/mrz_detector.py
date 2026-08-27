"""Computer-vision MRZ region detector for ICAO TD3 passports."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageOps

from app.core.logging.logger import get_logger

logger = get_logger(__name__)

TD3_LINE_COUNT = 2
TD3_CHARACTERS_PER_LINE = 44
TD3_EXPECTED_TOTAL_CHARS = TD3_LINE_COUNT * TD3_CHARACTERS_PER_LINE
TD3_SCORE_WEIGHTS = {
    "bottom_position": 0.15,
    "two_line_structure": 0.17,
    "aspect_ratio": 0.14,
    "width_ratio": 0.12,
    "character_density": 0.12,
    "component_count": 0.10,
    "uniform_spacing": 0.12,
    "td3_height": 0.08,
}


@dataclass(frozen=True)
class MRZDetectionFailure:
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MRZDetectionResult:
    crop: Image.Image | None
    bbox: tuple[int, int, int, int] | None
    score: float
    elapsed_ms: float
    candidate_count: int
    failure: MRZDetectionFailure | None = None
    debug: dict[str, Any] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return self.crop is not None and self.bbox is not None and self.failure is None


@dataclass(frozen=True)
class _Candidate:
    bbox: tuple[int, int, int, int]
    score: float
    metrics: dict[str, Any]


class MRZRegionDetector:
    """Detects the two TD3 MRZ lines without assuming a fixed image position."""

    def __init__(self, *, max_dimension: int = 1800, min_score: float = 0.62) -> None:
        self._max_dimension = max_dimension
        self._min_score = min_score

    def detect(self, image_bytes: bytes) -> MRZDetectionResult:
        started = time.perf_counter()
        try:
            import cv2
            import numpy as np
        except Exception as exc:
            return self._failure(started, "opencv_unavailable", {"error": str(exc)})

        try:
            gray = self._load_grayscale(image_bytes)
        except Exception as exc:
            return self._failure(started, "image_decode_failed", {"error": str(exc)})

        array = np.asarray(gray)
        height, width = array.shape[:2]
        if width < 240 or height < 160:
            return self._failure(started, "image_too_small", {"width": width, "height": height})

        threshold = self._mrz_text_mask(array, cv2)
        rows = self._row_activity(threshold, np)
        morphology_boxes = self._find_morphology_text_boxes(array, width, height, cv2, np)
        line_bands = self._dedupe_bands(
            [
                *self._find_line_bands(rows, height),
                *[(y, y + box_height) for _, y, _, box_height in morphology_boxes],
            ]
        )
        candidates = [
            *self._build_candidates(line_bands, threshold, width, height, cv2, np),
            *self._build_morphology_candidates(morphology_boxes, threshold, width, height, cv2, np),
        ]
        if not candidates:
            return self._failure(
                started,
                "no_mrz_candidate",
                {"width": width, "height": height, "line_band_count": len(line_bands)},
            )

        best = max(candidates, key=lambda item: item.score)
        if best.score < self._min_score:
            return self._failure(
                started,
                "low_confidence_mrz_candidate",
                {
                    "best_score": round(best.score, 3),
                    "best_bbox": best.bbox,
                    "best_metrics": best.metrics,
                    "candidate_count": len(candidates),
                },
            )

        crop = gray.crop(best.bbox)
        return MRZDetectionResult(
            crop=crop,
            bbox=best.bbox,
            score=round(best.score, 3),
            elapsed_ms=self._elapsed_ms(started),
            candidate_count=len(candidates),
            debug={"best_metrics": best.metrics, "image_size": (width, height)},
        )

    def _load_grayscale(self, image_bytes: bytes) -> Image.Image:
        with Image.open(io.BytesIO(image_bytes)) as raw_image:
            image = ImageOps.exif_transpose(raw_image).convert("RGB")
            image.thumbnail((self._max_dimension, self._max_dimension))
            return ImageOps.autocontrast(ImageOps.grayscale(image))

    @staticmethod
    def _mrz_text_mask(array: Any, cv2: Any) -> Any:
        blurred = cv2.GaussianBlur(array, (3, 3), 0)
        threshold = cv2.adaptiveThreshold(
            blurred,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            15,
        )
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1))
        return cv2.morphologyEx(threshold, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)

    @staticmethod
    def _row_activity(mask: Any, np: Any) -> Any:
        density = (mask > 0).mean(axis=1)
        kernel = np.ones(7, dtype=np.float32) / 7
        return np.convolve(density, kernel, mode="same")

    @staticmethod
    def _find_line_bands(
        rows: Any,
        image_height: int,
    ) -> list[tuple[int, int]]:
        threshold = max(float(rows.mean() + rows.std() * 0.45), 0.018)
        min_height = max(5, int(image_height * 0.006))
        max_height = max(18, int(image_height * 0.055))
        merge_gap = max(3, int(image_height * 0.012))
        bands: list[tuple[int, int]] = []
        start: int | None = None

        for index, value in enumerate(rows):
            if value >= threshold and start is None:
                start = index
            elif value < threshold and start is not None:
                if index - start >= min_height:
                    bands.append((start, index))
                start = None
        if start is not None and image_height - start >= min_height:
            bands.append((start, image_height - 1))

        merged: list[tuple[int, int]] = []
        for top, bottom in bands:
            if not merged or top - merged[-1][1] > merge_gap:
                merged.append((top, bottom))
            else:
                previous_top, _ = merged[-1]
                merged[-1] = (previous_top, bottom)

        return [(top, bottom) for top, bottom in merged if bottom - top <= max_height]

    def _build_candidates(
        self,
        line_bands: list[tuple[int, int]],
        mask: Any,
        width: int,
        height: int,
        cv2: Any,
        np: Any,
    ) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for first_index, first in enumerate(line_bands):
            for second in line_bands[first_index + 1 : first_index + 8]:
                candidate = self._score_pair(first, second, mask, width, height, cv2, np)
                if candidate is not None:
                    candidates.append(candidate)
        return candidates

    def _build_morphology_candidates(
        self,
        boxes: list[tuple[int, int, int, int]],
        mask: Any,
        width: int,
        height: int,
        cv2: Any,
        np: Any,
    ) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        ordered = sorted(boxes, key=lambda box: box[1])
        for first_index, first in enumerate(ordered):
            for second in ordered[first_index + 1 : first_index + 5]:
                candidate = self._score_box_pair(first, second, mask, width, height, cv2, np)
                if candidate is not None:
                    candidates.append(candidate)
        return candidates

    def _score_pair(
        self,
        first: tuple[int, int],
        second: tuple[int, int],
        mask: Any,
        width: int,
        height: int,
        cv2: Any,
        np: Any,
    ) -> _Candidate | None:
        top1, bottom1 = first
        top2, bottom2 = second
        if top2 <= bottom1:
            return None

        line_height_1 = bottom1 - top1 + 1
        line_height_2 = bottom2 - top2 + 1
        avg_line_height = (line_height_1 + line_height_2) / 2
        gap = top2 - bottom1
        if not (-avg_line_height * 0.45 <= gap <= avg_line_height * 2.4):
            return None

        top = max(0, int(top1 - avg_line_height * 0.55))
        bottom = min(height, int(bottom2 + avg_line_height * 0.65))
        band_mask = mask[top:bottom, :]
        columns = (band_mask > 0).mean(axis=0)
        active_columns = np.where(columns > max(float(columns.mean() + columns.std() * 0.18), 0.01))[0]
        if active_columns.size < width * 0.22:
            return None

        left = max(0, int(active_columns.min() - avg_line_height * 1.4))
        right = min(width, int(active_columns.max() + avg_line_height * 1.4))
        candidate_width = right - left
        candidate_height = bottom - top
        if candidate_width <= 0 or candidate_height <= 0:
            return None

        aspect = candidate_width / max(candidate_height, 1)
        if aspect < 5.0:
            return None

        candidate_mask = mask[top:bottom, left:right]
        density = float((candidate_mask > 0).mean())
        if density < 0.035:
            return None

        components = self._component_metrics(candidate_mask, cv2)
        if components["component_count"] < 35:
            return None
        structure = self._td3_structure_metrics(candidate_mask, cv2, np)
        if structure["line_count"] != TD3_LINE_COUNT:
            return None

        width_ratio = candidate_width / width
        bottom_position = bottom / height
        if bottom_position < 0.35:
            return None
        height_ratio = candidate_height / height
        normalized_gap = max(0.0, gap) / max(avg_line_height, 1)
        line_gap_score = 1.0 - min(1.0, abs(normalized_gap - 0.75) / 1.3)
        score = self._td3_score(
            aspect=aspect,
            width_ratio=width_ratio,
            density=density,
            component_count=components["component_count"],
            bottom_position=bottom_position,
            height_ratio=height_ratio,
            structure=structure,
            line_gap_score=line_gap_score,
        )

        metrics = {
            "source": "row_pair",
            "aspect": round(aspect, 2),
            "width_ratio": round(width_ratio, 3),
            "height_ratio": round(height_ratio, 3),
            "density": round(density, 3),
            "line_heights": (line_height_1, line_height_2),
            "line_gap": gap,
            "component_count": components["component_count"],
            "bottom_position": round(bottom_position, 3),
            **structure,
        }
        return _Candidate(bbox=(left, top, right, bottom), score=float(score), metrics=metrics)

    def _score_box_pair(
        self,
        first: tuple[int, int, int, int],
        second: tuple[int, int, int, int],
        mask: Any,
        width: int,
        height: int,
        cv2: Any,
        np: Any,
    ) -> _Candidate | None:
        x1, y1, w1, h1 = first
        x2, y2, w2, h2 = second
        bottom1 = y1 + h1
        bottom2 = y2 + h2
        gap = y2 - bottom1
        avg_line_height = (h1 + h2) / 2
        if not (-avg_line_height * 0.55 <= gap <= avg_line_height * 2.2):
            return None

        horizontal_overlap = min(x1 + w1, x2 + w2) - max(x1, x2)
        if horizontal_overlap < min(w1, w2) * 0.55:
            return None

        padding_x = int(avg_line_height * 0.50)
        padding_y = int(avg_line_height * 0.08)
        left = max(0, min(x1, x2) - padding_x)
        right = min(width, max(x1 + w1, x2 + w2) + padding_x)
        top = max(0, min(y1, y2) - padding_y)
        bottom = min(height, max(bottom1, bottom2) + padding_y)
        candidate_width = right - left
        candidate_height = bottom - top
        if candidate_width <= 0 or candidate_height <= 0:
            return None

        aspect = candidate_width / max(candidate_height, 1)
        width_ratio = candidate_width / width
        height_ratio = candidate_height / height
        bottom_position = bottom / height
        if aspect < 5.0 or bottom_position < 0.35:
            return None

        candidate_mask = mask[top:bottom, left:right]
        density = float((candidate_mask > 0).mean())
        components = self._component_metrics(candidate_mask, cv2)
        if density < 0.03 or components["component_count"] < 28:
            return None
        structure = self._td3_structure_metrics(candidate_mask, cv2, np)
        if structure["line_count"] != TD3_LINE_COUNT:
            return None

        normalized_gap = max(0.0, gap) / max(avg_line_height, 1)
        line_gap_score = 1.0 - min(1.0, abs(normalized_gap - 0.65) / 1.35)
        score = self._td3_score(
            aspect=aspect,
            width_ratio=width_ratio,
            density=density,
            component_count=components["component_count"],
            bottom_position=bottom_position,
            height_ratio=height_ratio,
            structure=structure,
            line_gap_score=line_gap_score,
        )
        metrics = {
            "source": "morphology_pair",
            "aspect": round(aspect, 2),
            "width_ratio": round(width_ratio, 3),
            "height_ratio": round(height_ratio, 3),
            "density": round(density, 3),
            "line_heights": (h1, h2),
            "line_gap": gap,
            "component_count": components["component_count"],
            "bottom_position": round(bottom_position, 3),
            **structure,
        }
        return _Candidate(bbox=(left, top, right, bottom), score=float(score), metrics=metrics)

    def _td3_score(
        self,
        *,
        aspect: float,
        width_ratio: float,
        density: float,
        component_count: int,
        bottom_position: float,
        height_ratio: float,
        structure: dict[str, Any],
        line_gap_score: float,
    ) -> float:
        aspect_score = self._range_score(aspect, low=8.0, high=32.0, soft_low=5.0, soft_high=45.0)
        width_score = self._range_score(width_ratio, low=0.45, high=0.98, soft_low=0.28, soft_high=1.0)
        density_score = self._range_score(density, low=0.045, high=0.22, soft_low=0.028, soft_high=0.34)
        component_score = self._range_score(
            component_count,
            low=TD3_EXPECTED_TOTAL_CHARS * 0.55,
            high=TD3_EXPECTED_TOTAL_CHARS * 1.25,
            soft_low=TD3_EXPECTED_TOTAL_CHARS * 0.30,
            soft_high=TD3_EXPECTED_TOTAL_CHARS * 1.75,
        )
        bottom_score = self._range_score(bottom_position, low=0.58, high=1.0, soft_low=0.35, soft_high=1.0)
        height_score = self._range_score(height_ratio, low=0.045, high=0.18, soft_low=0.025, soft_high=0.24)
        two_line_score = (
            structure["line_count_score"] * 0.45
            + structure["line_height_similarity"] * 0.30
            + line_gap_score * 0.25
        )
        return float(
            TD3_SCORE_WEIGHTS["bottom_position"] * bottom_score
            + TD3_SCORE_WEIGHTS["two_line_structure"] * two_line_score
            + TD3_SCORE_WEIGHTS["aspect_ratio"] * aspect_score
            + TD3_SCORE_WEIGHTS["width_ratio"] * width_score
            + TD3_SCORE_WEIGHTS["character_density"] * density_score
            + TD3_SCORE_WEIGHTS["component_count"] * component_score
            + TD3_SCORE_WEIGHTS["uniform_spacing"] * structure["uniform_spacing_score"]
            + TD3_SCORE_WEIGHTS["td3_height"] * height_score
        )

    @staticmethod
    def _dedupe_bands(bands: list[tuple[int, int]]) -> list[tuple[int, int]]:
        ordered = sorted((min(top, bottom), max(top, bottom)) for top, bottom in bands)
        deduped: list[tuple[int, int]] = []
        for top, bottom in ordered:
            if not deduped:
                deduped.append((top, bottom))
                continue
            previous_top, previous_bottom = deduped[-1]
            overlap = min(previous_bottom, bottom) - max(previous_top, top)
            smaller_height = max(1, min(previous_bottom - previous_top, bottom - top))
            if overlap / smaller_height > 0.55:
                deduped[-1] = (min(previous_top, top), max(previous_bottom, bottom))
            else:
                deduped.append((top, bottom))
        return deduped

    @staticmethod
    def _find_morphology_text_boxes(
        array: Any,
        width: int,
        height: int,
        cv2: Any,
        np: Any,
    ) -> list[tuple[int, int, int, int]]:
        rect_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 7))
        square_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 21))
        blackhat = cv2.morphologyEx(array, cv2.MORPH_BLACKHAT, rect_kernel)
        gradient = cv2.Sobel(blackhat, ddepth=cv2.CV_32F, dx=1, dy=0, ksize=-1)
        gradient = np.absolute(gradient)
        min_value, max_value = float(gradient.min()), float(gradient.max())
        gradient = ((gradient - min_value) / (max_value - min_value + 1e-5) * 255).astype("uint8")
        gradient = cv2.morphologyEx(gradient, cv2.MORPH_CLOSE, rect_kernel)
        threshold = cv2.threshold(gradient, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        threshold = cv2.morphologyEx(threshold, cv2.MORPH_CLOSE, square_kernel)
        threshold = cv2.erode(threshold, None, iterations=2)
        threshold = cv2.dilate(threshold, None, iterations=2)

        contours, _ = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes: list[tuple[int, int, int, int]] = []
        for contour in contours:
            x, y, box_width, box_height = cv2.boundingRect(contour)
            aspect = box_width / max(box_height, 1)
            width_ratio = box_width / width
            height_ratio = box_height / height
            bottom_position = (y + box_height) / height
            if (
                aspect >= 6.0
                and width_ratio >= 0.16
                and 0.02 <= height_ratio <= 0.12
                and bottom_position >= 0.35
            ):
                boxes.append((x, y, box_width, box_height))
        return boxes

    def _td3_structure_metrics(
        self,
        mask: Any,
        cv2: Any,
        np: Any,
    ) -> dict[str, Any]:
        row_density = (mask > 0).mean(axis=1)
        active_threshold = max(float(row_density.mean() + row_density.std() * 0.20), 0.012)
        raw_bands = self._active_bands(row_density, active_threshold, min_size=max(3, mask.shape[0] // 35))
        bands = self._merge_close_bands(raw_bands, max_gap=max(2, mask.shape[0] // 18))
        line_count = len(bands)
        line_count_score = 1.0 if line_count == TD3_LINE_COUNT else max(0.0, 1.0 - abs(line_count - TD3_LINE_COUNT) * 0.45)

        line_height_similarity = 0.0
        uniform_spacing_score = 0.0
        if line_count >= TD3_LINE_COUNT:
            selected = sorted(bands, key=lambda band: band[1] - band[0], reverse=True)[:TD3_LINE_COUNT]
            selected = sorted(selected)
            heights = [bottom - top + 1 for top, bottom in selected]
            avg_height = sum(heights) / len(heights)
            line_height_similarity = 1.0 - min(1.0, (max(heights) - min(heights)) / max(avg_height, 1.0))
            uniform_spacing_score = sum(
                self._line_spacing_score(mask[top : bottom + 1, :], cv2, np) for top, bottom in selected
            ) / TD3_LINE_COUNT

        return {
            "line_count": line_count,
            "line_count_score": round(line_count_score, 3),
            "line_height_similarity": round(line_height_similarity, 3),
            "uniform_spacing_score": round(uniform_spacing_score, 3),
        }

    @staticmethod
    def _active_bands(
        values: Any,
        threshold: float,
        *,
        min_size: int,
    ) -> list[tuple[int, int]]:
        bands: list[tuple[int, int]] = []
        start: int | None = None
        for index, value in enumerate(values):
            if value >= threshold and start is None:
                start = index
            elif value < threshold and start is not None:
                if index - start >= min_size:
                    bands.append((start, index - 1))
                start = None
        if start is not None and len(values) - start >= min_size:
            bands.append((start, len(values) - 1))
        return bands

    @staticmethod
    def _merge_close_bands(bands: list[tuple[int, int]], *, max_gap: int) -> list[tuple[int, int]]:
        merged: list[tuple[int, int]] = []
        for top, bottom in bands:
            if not merged or top - merged[-1][1] > max_gap:
                merged.append((top, bottom))
            else:
                previous_top, _ = merged[-1]
                merged[-1] = (previous_top, bottom)
        return merged

    @staticmethod
    def _line_spacing_score(line_mask: Any, cv2: Any, np: Any) -> float:
        contours, _ = cv2.findContours(line_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        centers: list[float] = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if 2 <= width <= 80 and 4 <= height <= 80:
                centers.append(x + width / 2)
        if len(centers) < TD3_CHARACTERS_PER_LINE * 0.35:
            return 0.0
        gaps = np.diff(sorted(centers))
        if gaps.size < 4:
            return 0.0
        median_gap = float(np.median(gaps))
        if median_gap <= 0:
            return 0.0
        normalized_gaps = gaps / median_gap
        regular_gaps = normalized_gaps[(normalized_gaps >= 0.35) & (normalized_gaps <= 2.7)]
        if regular_gaps.size < gaps.size * 0.65:
            return 0.35
        variation = float(np.std(regular_gaps))
        return max(0.0, min(1.0, 1.0 - variation / 0.85))

    @staticmethod
    def _component_metrics(mask: Any, cv2: Any) -> dict[str, Any]:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        count = 0
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if 2 <= width <= 80 and 4 <= height <= 80:
                count += 1
        return {"component_count": count}

    @staticmethod
    def _range_score(value: float, *, low: float, high: float, soft_low: float, soft_high: float) -> float:
        if low <= value <= high:
            return 1.0
        if value < low:
            return max(0.0, (value - soft_low) / max(low - soft_low, 0.001))
        return max(0.0, (soft_high - value) / max(soft_high - high, 0.001))

    def _failure(self, started: float, reason: str, details: dict[str, Any]) -> MRZDetectionResult:
        logger.info("mrz_region_detection_failed", reason=reason, **details)
        return MRZDetectionResult(
            crop=None,
            bbox=None,
            score=0.0,
            elapsed_ms=self._elapsed_ms(started),
            candidate_count=int(details.get("candidate_count") or 0),
            failure=MRZDetectionFailure(reason=reason, details=details),
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)
