"""Stream the existing canonical JSON format into a bounded SHA256 digest."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any


class ExcelSnapshotTooLarge(ValueError):
    pass


def snapshot_digest(value: Any, *, maximum_bytes: int | None = None) -> str:
    digest = hashlib.sha256()
    size = 0

    def emit(token: str) -> None:
        nonlocal size
        encoded = token.encode()
        size += len(encoded)
        if maximum_bytes is not None and size > maximum_bytes:
            raise ExcelSnapshotTooLarge("Excel source snapshot exceeds its size limit")
        digest.update(encoded)

    def visit(item: Any) -> None:
        if is_dataclass(item) and not isinstance(item, type):
            # Shallow field references avoid asdict's complete recursive copy.
            item = {field.name: getattr(item, field.name) for field in fields(item)}
        if isinstance(item, dict):
            mapped = {str(key): child for key, child in item.items()}
            emit("{")
            for index, key in enumerate(sorted(mapped)):
                if index:
                    emit(",")
                visit(key)
                emit(":")
                visit(mapped[key])
            emit("}")
        elif isinstance(item, (list, tuple)):
            emit("[")
            for index, child in enumerate(item):
                if index:
                    emit(",")
                visit(child)
            emit("]")
        elif isinstance(item, (date, datetime, uuid.UUID)):
            visit(str(item))
        elif isinstance(item, Enum):
            visit(item.value)
        elif isinstance(item, str):
            emit('"')
            for offset in range(0, len(item), 1024):
                emit(json.dumps(item[offset : offset + 1024])[1:-1])
            emit('"')
        elif item is None or type(item) in (int, float, bool):
            emit(json.dumps(item, allow_nan=False, separators=(",", ":")))
        else:
            raise ValueError("Unsupported export snapshot value")

    visit(value)
    return digest.hexdigest()
