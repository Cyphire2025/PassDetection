"""
WhatsApp broadcast planning DTOs.

These objects are intentionally disconnected from API routes. They define the
future WhatsApp integration contract without making messaging part of the main
Tour Ops workflow yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

WhatsAppMessageCategory = Literal["marketing", "utility", "authentication", "service"]
WhatsAppBroadcastIntent = Literal["welcome", "passport_upload_link", "attendance_qr"]


@dataclass(frozen=True, slots=True)
class WhatsAppRecipient:
    passenger_id: str
    full_name: str
    phone_number: str
    destination: str | None = None
    upload_link: str | None = None
    qr_payload: str | None = None


@dataclass(frozen=True, slots=True)
class WhatsAppTemplatePlan:
    intent: WhatsAppBroadcastIntent
    category: WhatsAppMessageCategory
    template_name: str
    language_code: str


@dataclass(frozen=True, slots=True)
class PlannedWhatsAppMessage:
    recipient: WhatsAppRecipient
    template: WhatsAppTemplatePlan
    variables: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WhatsAppBroadcastPlan:
    group_id: str
    group_name: str
    template: WhatsAppTemplatePlan
    messages: list[PlannedWhatsAppMessage]


@dataclass(frozen=True, slots=True)
class WhatsAppCostEstimate:
    market: str
    currency: str
    category: WhatsAppMessageCategory
    message_count: int
    unit_rate: Decimal
    estimated_total: Decimal
    notes: tuple[str, ...] = ()
