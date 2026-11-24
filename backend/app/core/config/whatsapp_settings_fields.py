"""WhatsApp provider and template settings with normalized field validation."""

from __future__ import annotations

import re

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

_WHATSAPP_API_VERSION_PATTERN = re.compile(r"^v[1-9][0-9]*\.0$")

_WHATSAPP_LANGUAGE_PATTERN = re.compile(r"^[a-z]{2,3}(?:_[A-Z]{2})?$")

_WHATSAPP_TEMPLATE_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,512}$")


class WhatsAppSettingsFields(BaseSettings):
    """Flat environment fields composed into the public Settings model."""

    whatsapp_access_token: str | None = Field(default=None, repr=False)
    whatsapp_phone_number_id: str | None = None
    whatsapp_api_version: str = "v25.0"
    whatsapp_template_language: str = "en_US"
    whatsapp_welcome_template_name: str = ""
    whatsapp_passport_link_template_name: str = ""
    whatsapp_reminder_template_name: str = "reminder_v1"
    whatsapp_update_template_name: str = ""
    whatsapp_group_invite_template_name: str = "whatsapp_group_invite_v1"
    whatsapp_group_invite_template_language: str = "en"
    whatsapp_document_template_name: str = "documents_v1"
    whatsapp_document_update_template_name: str = "pending_v1"
    whatsapp_document_update_template_language: str = "en"
    whatsapp_qr_template_name: str = "qrcode_v1"
    whatsapp_otp_template_name: str = ""
    whatsapp_otp_template_language: str = "en_US"
    whatsapp_delivery_concurrency: int = Field(default=4, ge=1, le=16)
    whatsapp_webhook_verify_token: str | None = Field(default=None, repr=False)
    whatsapp_app_secret: str | None = Field(default=None, repr=False)

    @field_validator("whatsapp_api_version")
    @classmethod
    def validate_whatsapp_api_version(cls, value: str) -> str:
        normalized = value.strip()
        if not _WHATSAPP_API_VERSION_PATTERN.fullmatch(normalized):
            raise ValueError("WHATSAPP_API_VERSION must use the form v25.0")
        return normalized

    @field_validator("whatsapp_phone_number_id")
    @classmethod
    def validate_whatsapp_phone_number_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized and not normalized.isascii():
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID must contain ASCII digits")
        if normalized and not normalized.isdigit():
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID must contain ASCII digits")
        return normalized or None

    @field_validator("whatsapp_otp_template_name")
    @classmethod
    def validate_whatsapp_otp_template_name(cls, value: str) -> str:
        normalized = value.strip()
        if normalized and not _WHATSAPP_TEMPLATE_NAME_PATTERN.fullmatch(normalized):
            raise ValueError(
                "WHATSAPP_OTP_TEMPLATE_NAME must contain only lowercase letters, "
                "numbers, and underscores"
            )
        return normalized

    @field_validator("whatsapp_otp_template_language", "whatsapp_group_invite_template_language")
    @classmethod
    def validate_whatsapp_otp_template_language(cls, value: str) -> str:
        normalized = value.strip()
        if not _WHATSAPP_LANGUAGE_PATTERN.fullmatch(normalized):
            raise ValueError(
                "WHATSAPP_OTP_TEMPLATE_LANGUAGE must be an approved Meta language code"
            )
        return normalized
