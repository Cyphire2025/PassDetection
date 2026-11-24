"""Exact Meta template header and body parameter representations."""

from __future__ import annotations

from typing import Any


def _text_parameter(value: str) -> dict[str, str]:
    return {"type": "text", "text": value}


def _image_parameter(media_id: str) -> dict[str, Any]:
    return {"type": "image", "image": {"id": media_id}}


def _document_parameter(media_id: str, filename: str) -> dict[str, Any]:
    return {
        "type": "document",
        "document": {"id": media_id, "filename": filename},
    }
