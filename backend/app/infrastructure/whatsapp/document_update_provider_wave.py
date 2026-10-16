"""Immutable update requests; concurrent HTTP never touches an ORM session."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.core.config.settings import Settings
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError
from app.infrastructure.whatsapp.document_delivery_runtime import PROVIDER_ATTEMPT_DEADLINE_SECONDS

UPDATE_SEND_CONCURRENCY = 4


@dataclass(frozen=True)
class UpdateProviderRequest:
    log_id: uuid.UUID
    phone: str
    template: str
    language: str
    message: str


@dataclass(frozen=True)
class UpdateProviderOutcome:
    log_id: uuid.UUID
    status: str
    error: str | None = None
    provider_id: str | None = None
    updated_at: datetime | None = None


async def send_update_wave(
    requests: Sequence[UpdateProviderRequest],
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    send: Callable[..., Awaitable[str]],
) -> list[UpdateProviderOutcome]:
    """Finish every bounded attempt before the coordinator releases source locks."""
    if len(requests) > UPDATE_SEND_CONCURRENCY:
        raise ValueError("An update wave cannot exceed four provider requests")

    async def attempt(request: UpdateProviderRequest) -> UpdateProviderOutcome:
        provider_id = None
        try:
            async with asyncio.timeout(PROVIDER_ATTEMPT_DEADLINE_SECONDS):
                provider_id = await send(
                    client=client, settings=settings, to_number=request.phone,
                    template_name=request.template, language_code=request.language,
                    message_content=request.message,
                )
            status, error = "submitted", None
        except WhatsAppCloudApiError as exc:
            status = "delivery_unknown" if exc.delivery_unknown else "failed"
            error = exc.persistence_message[:2000]
        except Exception:
            status, error = (
                "delivery_unknown", "Update outcome is unknown; automatic resend is suppressed.",
            )
        return UpdateProviderOutcome(request.log_id, status, error, provider_id, datetime.now(UTC))

    return list(await asyncio.gather(*(attempt(request) for request in requests)))
