"""OpenAI vision fallback isolated from the local OCR pipeline."""

from __future__ import annotations

import base64
import json
from typing import Any, Protocol

try:
    import httpx
except Exception:  # pragma: no cover - depends on optional runtime package availability
    httpx = None  # type: ignore[assignment]


class VisionSettings(Protocol):
    model: str
    timeout_seconds: float


class OpenAIVisionFallback:
    """Calls the configured vision model and returns untrusted field candidates."""

    _FIELD_NAMES = (
        "surname",
        "given_names",
        "passport_number",
        "nationality",
        "issuing_country",
        "date_of_birth",
        "date_of_expiry",
        "sex",
    )

    def __init__(self, settings: VisionSettings) -> None:
        self._settings = settings

    async def extract(
        self,
        image_bytes: bytes,
        *,
        content_type: str,
        local_fields: dict[str, str],
        api_key: str,
    ) -> dict[str, Any]:
        if httpx is None:
            return {}

        media_type = content_type if content_type.startswith("image/") else "image/jpeg"
        image_url = f"data:{media_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        payload = self._payload(image_url=image_url, local_fields=local_fields)

        async with httpx.AsyncClient(timeout=self._settings.timeout_seconds) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()

        text = self._response_text(response.json())
        parsed = json.loads(text) if text else {}
        return parsed if isinstance(parsed, dict) else {}

    def _payload(self, *, image_url: str, local_fields: dict[str, str]) -> dict[str, Any]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {field: {"type": "string"} for field in self._FIELD_NAMES},
            "required": list(self._FIELD_NAMES),
        }
        return {
            "model": self._settings.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are validating an existing local OCR result against this "
                                "passport image. Compare the OCR fields with the image, correct "
                                "only clear mismatches, and leave any unreadable field empty. "
                                "Do not invent missing values. Use YYYY-MM-DD for dates. "
                                "For sex use M, F, X, or empty string. "
                                "Current local OCR fields: "
                                f"{json.dumps(local_fields, ensure_ascii=True)}"
                            ),
                        },
                        {"type": "input_image", "image_url": image_url},
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "passport_fields",
                    "schema": schema,
                    "strict": True,
                }
            },
        }

    @staticmethod
    def _response_text(data: dict[str, Any]) -> str | None:
        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        for item in data.get("output", []):
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                    text = content.get("text")
                    if isinstance(text, str):
                        return text
        return None
