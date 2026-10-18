"""Per-route transport bounds, shared by Gunicorn and real loopback qualification."""

from typing import Any

from uvicorn.protocols.websockets.websockets_impl import WebSocketProtocol
from websockets.datastructures import Headers
from websockets.legacy.server import HTTPResponse

AI_VOICE_PATH = "/api/v1/ai-assistant/voice"
AI_VOICE_MESSAGE_BYTES = 32 * 1024


class BoundedWebSocketProtocol(WebSocketProtocol):
    """Allow bounded PCM packets only on the accepted native-voice route."""

    async def process_request(self, path: str, request_headers: Headers) -> HTTPResponse | None:
        response = await super().process_request(path, request_headers)
        # ASGI has already authorized and accepted this route. A 100 ms PCM
        # packet is ~4.3 KiB in JSON; 32 KiB also covers 8,000 text characters.
        # Similar-looking paths and all realtime hint routes keep the 1 KiB cap.
        if response is None and self.scope["path"] == self.root_path + AI_VOICE_PATH:
            self.max_size = AI_VOICE_MESSAGE_BYTES
        return response


BOUNDED_WEBSOCKET_OPTIONS: dict[str, Any] = {
    "ws": BoundedWebSocketProtocol,
    "ws_max_size": 1_024,
    "ws_max_queue": 4,
    # Compression stays off for both PCM and the tiny realtime hints.
    "ws_per_message_deflate": False,
}
