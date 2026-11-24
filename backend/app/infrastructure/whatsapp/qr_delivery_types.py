"""Explicit call-time dependencies for QR media and private dispatch phases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    PassengerQRTokenModel,
    PassengerQrWhatsAppDeliveryModel,
)
from app.infrastructure.whatsapp.private_delivery_policy import PrivateDeliveryRecipientValidation

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True, slots=True)
class QrMediaCallbacks:
    session_factory: SessionFactory
    source_statement: Callable[
        ..., Select[tuple[PassengerQrWhatsAppDeliveryModel, PassengerQRTokenModel]]
    ]
    mark_delivery: Callable[..., Awaitable[None]]
    qr_status: Callable[[PassengerQRTokenModel], str]
    render: Callable[[str], bytes]
    upload: Callable[..., Awaitable[str]]


@dataclass(frozen=True, slots=True)
class QrDispatchCallbacks:
    session_factory: SessionFactory
    validate_recipient: Callable[..., Awaitable[PrivateDeliveryRecipientValidation]]
    validate_welcome: Callable[..., Awaitable[PrivateDeliveryRecipientValidation]]
    qr_status: Callable[[PassengerQRTokenModel], str]
    send_template: Callable[..., Awaitable[str]]
    commit_outcome: Callable[..., Awaitable[None]]
