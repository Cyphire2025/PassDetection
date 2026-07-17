"""Label-anchored date-of-issue extractor for passport data pages."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from PIL import Image, ImageOps

from app.core.config.settings import get_settings
from app.infrastructure.ocr.roi.base import ROIExtractionResult
from app.infrastructure.ocr.roi.common import ROIImageTools


class DateOfIssueROIExtractor:
    """Read a printed issue date only when its label and value are both clear."""

    field_name = "date_of_issue"
    source = "roi_date_of_issue"

    # Indian passport layouts place the issue/expiry block in the lower data
    # area. The broad crop keeps this usable across older and newer layouts;
    # the label anchor prevents an adjacent birth/expiry date from being used.
    _search_roi = (0.18, 0.34, 1.00, 0.90)
    _label_pattern = re.compile(r"\bDATE\s*(?:OF\s*)?ISSU[E3]\b", re.IGNORECASE)
    _numeric_date = re.compile(r"\b(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})\b")
    _iso_date = re.compile(r"\b(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})\b")
    _named_date = re.compile(
        r"\b(\d{1,2})\s+"
        r"(JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|"
        r"JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?|OCT(?:OBER)?|NOV(?:EMBER)?|"
        r"DEC(?:EMBER)?)"
        r"\s+(\d{4})\b",
        re.IGNORECASE,
    )

    def extract(self, image: Image.Image) -> ROIExtractionResult | None:
        search_crop = ROIImageTools.relative_crop(image, self._search_roi)
        prepared = ImageOps.autocontrast(ImageOps.grayscale(search_crop))
        search_crop.close()
        if prepared.height < 700:
            scale = 700 / max(1, prepared.height)
            resized = prepared.resize(
                (max(1, round(prepared.width * scale)), 700),
                Image.Resampling.LANCZOS,
            )
            prepared.close()
            prepared = resized
        expanded = ImageOps.expand(prepared, border=(24, 20, 24, 20), fill=255)
        prepared.close()
        prepared = expanded
        prepared.info["dpi"] = (300, 300)

        try:
            import pytesseract
            from pytesseract import Output

            data = pytesseract.image_to_data(
                prepared,
                config="--oem 1 --dpi 300 -l eng --psm 6",
                output_type=Output.DICT,
                timeout=get_settings().roi_field_timeout_seconds,
            )
        except Exception:
            return None
        finally:
            prepared.close()

        candidate = self._select_candidate(data)
        if candidate is None:
            return None
        value, confidence, line_number = candidate
        return ROIExtractionResult(
            field_name=self.field_name,
            value=value,
            confidence=confidence,
            source=self.source,
            debug={
                "search_roi": self._search_roi,
                "label_anchor": "date_of_issue",
                "line_offset": line_number,
            },
        )

    def _select_candidate(self, data: dict[str, Any]) -> tuple[str, float, int] | None:
        lines: dict[tuple[int, int, int, int], list[tuple[str, float]]] = defaultdict(list)
        texts = data.get("text", [])
        for index, raw_text in enumerate(texts):
            text = str(raw_text).strip()
            confidence = self._confidence_at(data, index)
            if not text or confidence < 0:
                continue
            key = (
                self._int_at(data, "page_num", index),
                self._int_at(data, "block_num", index),
                self._int_at(data, "par_num", index),
                self._int_at(data, "line_num", index),
            )
            lines[key].append((text, confidence))

        ordered = [
            (
                " ".join(token for token, _ in tokens),
                sum(confidence for _, confidence in tokens) / max(1, len(tokens)),
            )
            for _, tokens in sorted(lines.items())
        ]
        for label_index, (label_line, label_confidence) in enumerate(ordered):
            if label_confidence < 45 or not self._label_pattern.search(label_line):
                continue
            for offset, (candidate_line, candidate_confidence) in enumerate(
                ordered[label_index:label_index + 3]
            ):
                # On the label line, ignore text before the label. On following
                # lines, require a high-confidence date to avoid selecting the
                # neighbouring expiry or birth field.
                search_text = candidate_line
                if offset == 0:
                    label_match = self._label_pattern.search(candidate_line)
                    search_text = candidate_line[label_match.end():] if label_match else ""
                value = self.parse_date(search_text)
                minimum_confidence = 62 if offset == 0 else 76
                if value and candidate_confidence >= minimum_confidence:
                    return value, round(min(0.99, candidate_confidence / 100), 3), offset
        return None

    @classmethod
    def parse_date(cls, value: str) -> str | None:
        """Normalize supported printed date forms to ISO, rejecting future dates."""

        normalized = " ".join(value.upper().strip().split())
        match = cls._iso_date.search(normalized)
        if match:
            parsed = cls._safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            return parsed.isoformat() if parsed else None

        match = cls._numeric_date.search(normalized)
        if match:
            parsed = cls._safe_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            return parsed.isoformat() if parsed else None

        match = cls._named_date.search(normalized)
        if match:
            try:
                parsed = datetime.strptime(
                    f"{int(match.group(1)):02d} {match.group(2)[:3]} {match.group(3)}",
                    "%d %b %Y",
                ).date()
            except ValueError:
                return None
            return parsed.isoformat() if cls._plausible(parsed) else None
        return None

    @staticmethod
    def _safe_date(year: int, month: int, day: int) -> date | None:
        try:
            parsed = date(year, month, day)
        except ValueError:
            return None
        return parsed if DateOfIssueROIExtractor._plausible(parsed) else None

    @staticmethod
    def _plausible(value: date) -> bool:
        return date(1900, 1, 1) <= value <= date.today()

    @staticmethod
    def _int_at(data: dict[str, Any], key: str, index: int) -> int:
        try:
            return int(data.get(key, [0])[index])
        except (IndexError, TypeError, ValueError):
            return 0

    @staticmethod
    def _confidence_at(data: dict[str, Any], index: int) -> float:
        try:
            return float(data.get("conf", [-1])[index])
        except (IndexError, TypeError, ValueError):
            return -1.0
