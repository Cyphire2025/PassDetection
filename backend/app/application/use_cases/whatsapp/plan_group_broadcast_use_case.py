"""
Build WhatsApp broadcast plans without sending messages.

This is intentionally a pure planner so future UI/API work can preview exactly
who would receive which template before any BSP integration is enabled.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.dtos.whatsapp_dtos import (
    PlannedWhatsAppMessage,
    WhatsAppBroadcastIntent,
    WhatsAppBroadcastPlan,
    WhatsAppRecipient,
    WhatsAppTemplatePlan,
)
from app.core.config.settings import get_settings


@dataclass(frozen=True, slots=True)
class PlanGroupBroadcastInput:
    group_id: str
    group_name: str
    recipients: list[WhatsAppRecipient]
    intent: WhatsAppBroadcastIntent
    language_code: str | None = None


class PlanGroupBroadcastUseCase:
    def execute(self, request: PlanGroupBroadcastInput) -> WhatsAppBroadcastPlan:
        template = template_for_intent(request.intent, request.language_code)
        messages = [
            PlannedWhatsAppMessage(
                recipient=recipient,
                template=template,
                variables=variables_for_recipient(request.group_name, request.intent, recipient),
            )
            for recipient in request.recipients
            if recipient.phone_number.strip()
        ]
        return WhatsAppBroadcastPlan(
            group_id=request.group_id,
            group_name=request.group_name,
            template=template,
            messages=messages,
        )


def template_for_intent(
    intent: WhatsAppBroadcastIntent,
    language_code: str | None = None,
) -> WhatsAppTemplatePlan:
    settings = get_settings()
    resolved_language_code = language_code or settings.whatsapp_template_language
    if intent == "welcome":
        return WhatsAppTemplatePlan(
            intent=intent,
            category="marketing",
            template_name=settings.whatsapp_welcome_template_name,
            language_code=resolved_language_code,
        )
    if intent == "passport_upload_link":
        return WhatsAppTemplatePlan(
            intent=intent,
            category="utility",
            template_name=settings.whatsapp_passport_link_template_name,
            language_code=resolved_language_code,
        )
    return WhatsAppTemplatePlan(
        intent=intent,
        category="utility",
        template_name="tour_attendance_qr_v1",
        language_code=resolved_language_code,
    )


def variables_for_recipient(
    group_name: str,
    intent: WhatsAppBroadcastIntent,
    recipient: WhatsAppRecipient,
) -> dict[str, str]:
    variables = {
        "name": recipient.full_name,
        "group_name": group_name,
        "destination": recipient.destination or "",
    }
    if intent == "passport_upload_link":
        variables["upload_link"] = recipient.upload_link or ""
    if intent == "attendance_qr":
        variables["qr_payload"] = recipient.qr_payload or ""
    return variables
