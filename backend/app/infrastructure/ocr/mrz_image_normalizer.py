"""MRZ-specific image normalization before OCR."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageOps


@dataclass(frozen=True)
class MRZImageNormalizerConfig:
    target_text_height: int = 56
    line_canvas_height: int = 84
    horizontal_margin: int = 110
    vertical_margin: int = 20
    line_gap: int = 10
    max_upscale: float = 1.5


class MRZImageNormalizer:
    """Produces one OCR-ready image from a detected two-line TD3 MRZ crop."""

    def __init__(self, config: MRZImageNormalizerConfig | None = None) -> None:
        self._config = config or MRZImageNormalizerConfig()

    def normalize(self, crop: Image.Image) -> Image.Image:
        try:
            import cv2
            import numpy as np
        except Exception:
            image = ImageOps.autocontrast(ImageOps.grayscale(crop))
            image = image.resize(self._fallback_size(image), Image.Resampling.LANCZOS)
            return self._with_dpi(image)

        gray = ImageOps.grayscale(crop)
        array = np.asarray(gray, dtype=np.uint8)
        array = self._contrast_stretch(array, np)
        array = self._deskew_block(array, cv2, np, min_angle=1.0, max_angle=6.0)
        line_bands = self._detect_line_bands(array, cv2, np)
        line_images = [self._normalize_line(array[top:bottom], cv2, np) for top, bottom in line_bands]
        if len(line_images) != 2:
            resized = self._resize_whole_crop(array, cv2)
            return self._with_dpi(Image.fromarray(resized))
        combined = self._combine_lines(line_images, cv2, np)
        return self._with_dpi(Image.fromarray(combined))

    def _detect_line_bands(self, array, cv2, np) -> list[tuple[int, int]]:  # type: ignore[no-untyped-def]
        threshold = cv2.adaptiveThreshold(
            array,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            13,
        )
        row_density = (threshold > 0).mean(axis=1)
        active_threshold = max(float(row_density.mean() + row_density.std() * 0.20), 0.018)
        active_rows = np.where(row_density >= active_threshold)[0]
        if active_rows.size == 0:
            return self._fallback_line_bands(array.shape[0])

        top = int(active_rows[0])
        bottom = int(active_rows[-1]) + 1
        candidate_gaps = []
        previous = int(active_rows[0])
        min_gap = max(4, array.shape[0] // 28)
        for row in active_rows[1:]:
            current = int(row)
            gap = current - previous
            if gap >= min_gap:
                center = previous + gap / 2
                candidate_gaps.append((gap, abs(center - (top + bottom) / 2), previous, current))
            previous = current

        if candidate_gaps:
            _, _, gap_start, gap_end = sorted(candidate_gaps, key=lambda item: (-item[0], item[1]))[0]
            split = (gap_start + gap_end) // 2
        else:
            split = (top + bottom) // 2

        min_line_height = max(8, int((bottom - top) * 0.18))
        if split - top < min_line_height or bottom - split < min_line_height:
            return self._fallback_line_bands(array.shape[0])

        return [
            self._pad_band(0, split, top, split),
            self._pad_band(split, array.shape[0], split, bottom),
        ]

    @staticmethod
    def _pad_band(minimum: int, maximum: int, top: int, bottom: int) -> tuple[int, int]:
        height = bottom - top
        margin = max(5, int(height * 0.28))
        return max(minimum, top - margin), min(maximum, bottom + margin)

    @staticmethod
    def _fallback_line_bands(height: int) -> list[tuple[int, int]]:
        midpoint = height // 2
        return [(0, midpoint), (midpoint, height)]

    def _normalize_line(self, array, cv2, np):  # type: ignore[no-untyped-def]
        line = self._deskew_line(array, cv2, np)
        line = self._trim_line_foreground(line, cv2, np)
        line = self._local_contrast(line, cv2)
        line = self._preserve_edges(line, cv2)
        line = self._resize_line_to_text_height(line, cv2)
        return line

    def _deskew_line(self, array, cv2, np):  # type: ignore[no-untyped-def]
        return self._deskew_block(array, cv2, np, min_angle=0.15, max_angle=3.0)

    def _deskew_block(self, array, cv2, np, *, min_angle: float, max_angle: float):  # type: ignore[no-untyped-def]
        threshold = cv2.threshold(array, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        points = cv2.findNonZero(threshold)
        if points is None or len(points) < 25:
            return array
        rect = cv2.minAreaRect(points)
        angle = self._normalized_skew_angle(float(rect[-1]))
        if abs(angle) < min_angle or abs(angle) > max_angle:
            return array
        height, width = array.shape[:2]
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
        return cv2.warpAffine(
            array,
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=255,
        )

    @staticmethod
    def _normalized_skew_angle(angle: float) -> float:
        if angle > 45:
            return angle - 90
        if angle < -45:
            return 90 + angle
        return angle

    def _trim_line_foreground(self, array, cv2, np):  # type: ignore[no-untyped-def]
        threshold = cv2.adaptiveThreshold(
            array,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            13,
        )
        points = cv2.findNonZero(threshold)
        if points is None:
            return array
        x, y, width, height = cv2.boundingRect(points)
        if width < array.shape[1] * 0.35 or height < array.shape[0] * 0.20:
            return array
        margin_y = max(4, int(height * 0.35))
        margin_x = max(8, int(height * 0.45))
        return array[
            max(0, y - margin_y) : min(array.shape[0], y + height + margin_y),
            max(0, x - margin_x) : min(array.shape[1], x + width + margin_x),
        ]

    @staticmethod
    def _local_contrast(array, cv2):  # type: ignore[no-untyped-def]
        return cv2.normalize(array, None, 0, 255, cv2.NORM_MINMAX)

    @staticmethod
    def _preserve_edges(array, cv2):  # type: ignore[no-untyped-def]
        blur = cv2.GaussianBlur(array, (0, 0), sigmaX=0.55)
        return cv2.addWeighted(array, 1.12, blur, -0.12, 0)

    def _resize_line_to_text_height(self, array, cv2):  # type: ignore[no-untyped-def]
        foreground_height = self._foreground_height(array, cv2)
        scale = min(self._config.target_text_height / max(1, foreground_height), self._config.max_upscale)
        target_width = max(1, round(array.shape[1] * scale))
        target_height = max(1, round(array.shape[0] * scale))
        interpolation = cv2.INTER_CUBIC if scale >= 1 else cv2.INTER_AREA
        return cv2.resize(array, (target_width, target_height), interpolation=interpolation)

    @staticmethod
    def _foreground_height(array, cv2) -> int:  # type: ignore[no-untyped-def]
        threshold = cv2.threshold(array, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        points = cv2.findNonZero(threshold)
        if points is None:
            return array.shape[0]
        _, _, _, height = cv2.boundingRect(points)
        return max(1, height)

    def _combine_lines(self, line_images, cv2, np):  # type: ignore[no-untyped-def]
        target_width = max(line.shape[1] for line in line_images) + self._config.horizontal_margin * 2
        canvases = [self._line_canvas(line, target_width, np) for line in line_images]
        height = (
            self._config.vertical_margin * 2
            + self._config.line_gap
            + sum(canvas.shape[0] for canvas in canvases)
        )
        combined = np.full((height, target_width), 255, dtype=np.uint8)
        y = self._config.vertical_margin
        for canvas in canvases:
            combined[y : y + canvas.shape[0], :] = canvas
            y += canvas.shape[0] + self._config.line_gap
        return combined

    def _line_canvas(self, line, target_width: int, np):  # type: ignore[no-untyped-def]
        canvas = np.full((self._config.line_canvas_height, target_width), 255, dtype=np.uint8)
        x = self._config.horizontal_margin
        y = max(0, (self._config.line_canvas_height - line.shape[0]) // 2)
        max_width = min(line.shape[1], target_width - x)
        max_height = min(line.shape[0], self._config.line_canvas_height - y)
        canvas[y : y + max_height, x : x + max_width] = line[:max_height, :max_width]
        return canvas

    def _resize_whole_crop(self, array, cv2):  # type: ignore[no-untyped-def]
        scale = (self._config.line_canvas_height * 2) / max(1, array.shape[0])
        resized = cv2.resize(
            array,
            (max(1, round(array.shape[1] * scale)), self._config.line_canvas_height * 2),
            interpolation=cv2.INTER_CUBIC if scale >= 1 else cv2.INTER_AREA,
        )
        return cv2.copyMakeBorder(
            resized,
            self._config.vertical_margin,
            self._config.vertical_margin,
            self._config.horizontal_margin,
            self._config.horizontal_margin,
            cv2.BORDER_CONSTANT,
            value=255,
        )

    @staticmethod
    def _contrast_stretch(array, np):  # type: ignore[no-untyped-def]
        low, high = np.percentile(array, (1.0, 99.0))
        if high <= low:
            return array
        stretched = (array.astype("float32") - low) * (255.0 / (high - low))
        return np.clip(stretched, 0, 255).astype("uint8")

    def _fallback_size(self, image: Image.Image) -> tuple[int, int]:
        if image.height <= 0:
            return image.size
        target_height = self._config.line_canvas_height * 2
        scale = target_height / image.height
        return max(1, round(image.width * scale)), target_height

    @staticmethod
    def _with_dpi(image: Image.Image) -> Image.Image:
        image.info["dpi"] = (300, 300)
        return image
