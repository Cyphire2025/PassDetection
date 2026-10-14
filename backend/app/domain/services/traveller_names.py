"""Whole-name components only; no initials expansion, edit distance or OCR repair."""

from collections.abc import Mapping


def compatible_name_words(left: str, right: str) -> bool:
    """O(L) time/space; inputs are already normalized and bounded by identity parsing."""
    first, second = frozenset(left.split()), frozenset(right.split())
    return bool(first and second and (first <= second or second <= first))


def passport_holder_name(fields: Mapping[str, object]) -> str | None:
    """Compose authoritative reviewed passport fields, preserving full-name order."""
    parts = [fields.get(key) for key in ("given_names", "surname")]
    if any(value is not None and not isinstance(value, str) for value in parts):
        return None
    name = " ".join(" ".join(value.split()) for value in parts if isinstance(value, str) and value.strip())
    return name if 1 <= len(name) <= 255 else None
