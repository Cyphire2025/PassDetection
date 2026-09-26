"""Explicit file representations for OpenAPI (no JSON success placeholder)."""

from typing import Any

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def binary_responses(
    *media_types: str, range_requests: bool = False
) -> dict[int | str, dict[str, Any]]:
    response: dict[str, Any] = {
        "description": "Authorized file content",
        "content": {
            media: {"schema": {"type": "string", "format": "binary"}} for media in media_types
        },
        "headers": {
            "Content-Disposition": {"schema": {"type": "string"}},
            "Cache-Control": {"schema": {"type": "string"}},
        },
    }
    responses: dict[int | str, dict[str, Any]] = {200: response}
    if range_requests:
        responses[206] = {
            **response,
            "description": "Requested byte range",
            "headers": {**response["headers"], "Content-Range": {"schema": {"type": "string"}}},
        }
    return responses
