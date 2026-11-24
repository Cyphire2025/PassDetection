"""Static factual-anchor and minimization patterns for untrusted email text."""

from __future__ import annotations

import re
from typing import Final

_EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    re.IGNORECASE,
)

_URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"https?://[^\s<>{}\"]+", re.IGNORECASE)

_PASSPORT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(passport(?:\s+(?:number|no\.?))?)\s*[:#-]?\s*[A-Z0-9]{5,16}\b"
)

_DOB_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:date\s+of\s+birth|dob)\s*[:#-]?\s*"
    r"(?:\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}-\d{2}-\d{2})"
)

_PHONE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:phone|mobile|contact)\s*[:#-]?\s*\+?[\d() .-]{7,24}"
)

_INTERNATIONAL_PHONE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\w)\+\d(?:[\d() .-]{6,22}\d)"
)

_FACT_PHONE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?:\b(?:phone|mobile|contact)\s*[:#-]?\s*\+?[\d() .-]{7,24}"
    r"|(?<!\w)\+\d(?:[\d() .-]{6,22}\d))"
)

_FACT_PASSPORT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\bpassport(?:\s+(?:number|no\.?|id))?\s*[:#-]?\s*"
    r"(?P<anchor>(?=[A-Z0-9]{5,16}\b)(?=[A-Z0-9]*\d)"
    r"[A-Z0-9]{5,16})\b"
)

_FACT_LABELED_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:flight|pnr|booking|reference|ref|confirmation|ticket)"
    r"(?:\s+(?:number|no\.?|code|id))?\s*[:#-]?\s*"
    r"(?P<anchor>(?:[A-Z]{2,3}\s?-?\d{2,4}[A-Z]?)|"
    r"(?:(?=[A-Z0-9/-]{3,24}\b)(?=[A-Z0-9/-]*\d)"
    r"[A-Z0-9][A-Z0-9/-]{2,23}))\b"
)

_FACT_MIXED_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?=[A-Za-z0-9-]{4,24}\b)(?=[A-Za-z0-9-]*[A-Za-z])"
    r"(?=[A-Za-z0-9-]*\d)[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\b"
)

_FACT_MONEY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?:[$\u20ac\u00a3\u20b9]\s*\d[\d,]*(?:\.\d{1,2})?"
    r"|(?:INR|USD|EUR|GBP|AED|SGD|JPY|RS\.?|RUPEES?)\s*"
    r"\d[\d,]*(?:\.\d{1,2})?"
    r"|\d[\d,]*(?:\.\d{1,2})?\s*"
    r"(?:INR|USD|EUR|GBP|AED|SGD|JPY|RS\.?|RUPEES?))"
)

_MONTH_PATTERN: Final[str] = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)

_FACT_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"(?i)\b(?:\d{{4}}[-/.]\d{{1,2}}[-/.]\d{{1,2}}"
    rf"|\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{2,4}}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH_PATTERN}"
    rf"(?:\s+\d{{2,4}})?"
    rf"|{_MONTH_PATTERN}\s+\d{{4}}"
    rf"|{_MONTH_PATTERN}\s+\d{{1,2}}(?:st|nd|rd|th)?"
    rf"(?:,\s*|\s+)?\d{{2,4}})\b"
)

_FACT_TIME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:(?:[01]?\d|2[0-3]):[0-5]\d"
    r"(?:\s*(?:a\.?m\.?|p\.?m\.?))?"
    r"|(?:1[0-2]|0?[1-9])\s*(?:a\.?m\.?|p\.?m\.?)"
    r"|noon|midnight|eod|cob)\b"
)

_FACT_TEMPORAL_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:today|tomorrow|yesterday|monday|tuesday|wednesday|"
    r"thursday|friday|saturday|sunday)\b"
)

_FACT_NUMBER_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<![\w])\d+(?:[,.]\d+)*(?:%|(?=\b))")

_FACTUAL_ANCHOR_RULES: Final[tuple[tuple[str, re.Pattern[str], str | None], ...]] = (
    ("url", _URL_PATTERN, None),
    ("email", _EMAIL_PATTERN, None),
    ("phone", _FACT_PHONE_PATTERN, None),
    ("passport", _FACT_PASSPORT_PATTERN, "anchor"),
    ("money", _FACT_MONEY_PATTERN, None),
    ("date", _FACT_DATE_PATTERN, None),
    ("time", _FACT_TIME_PATTERN, None),
    ("reference", _FACT_LABELED_CODE_PATTERN, "anchor"),
    ("reference", _FACT_MIXED_CODE_PATTERN, None),
    ("date", _FACT_TEMPORAL_WORD_PATTERN, None),
    ("number", _FACT_NUMBER_PATTERN, None),
)

_SAFE_DEADLINE_DERIVATIONS: Final[dict[str, frozenset[str]]] = {
    "tomorrow evening": frozenset({"kal shaam", "kal shaam tak"}),
}
