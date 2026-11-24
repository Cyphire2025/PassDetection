"""Bounded provider diagnostics and fixed delivery-failure wording."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class WhatsAppCloudApiError(RuntimeError):
    """A safe provider error suitable for per-recipient message logs."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "WHATSAPP_PROVIDER_ERROR",
        transient: bool = False,
        delivery_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient
        self.delivery_unknown = delivery_unknown

    @property
    def persistence_message(self) -> str:
        """Return a bounded diagnostic that is safe to expose to staff clients."""

        return f"{self.code}: {self}"


def _meta_code(value: object) -> str | None:
    """Accept bounded decimal identifiers, never arbitrary provider response text."""
    if type(value) is int and 0 <= value < 10**20:
        return str(value)
    if isinstance(value, str):
        candidate = value.strip()
        if 0 < len(candidate) <= 20 and candidate.isascii() and candidate.isdigit():
            return candidate
    return None


def _meta_error_reference(data: Any) -> tuple[str | None, str | None, str]:
    """Return non-sensitive Meta error identifiers for staff diagnostics."""

    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return None, None, ""
    meta_code = _meta_code(error.get("code"))
    meta_subcode = _meta_code(error.get("error_subcode"))
    parts = []
    if meta_code:
        parts.append(f"Meta code {meta_code}")
    if meta_subcode:
        parts.append(f"subcode {meta_subcode}")
    return meta_code, meta_subcode, f" ({', '.join(parts)})" if parts else ""


@dataclass(frozen=True, slots=True)
class TemplateDeliveryDiagnostics:
    interrupted_message: str
    rate_limited_message: str
    rejected_message: str
    accepted_without_id: str
    log_event: str
    code_log_key: str = "meta_error_code"
    subcode_log_key: str = "meta_error_subcode"


STANDARD_TEMPLATE_DIAGNOSTICS = TemplateDeliveryDiagnostics(
    interrupted_message="WhatsApp delivery outcome is unknown after a provider connection interruption",
    rate_limited_message="Meta temporarily rate-limited this template message",
    rejected_message="Meta rejected this template message; verify the approved template configuration and recipient details",
    accepted_without_id="WhatsApp API accepted the request without returning a message ID",
    log_event="whatsapp_cloud_api_request_rejected",
    code_log_key="provider_code",
    subcode_log_key="provider_subcode",
)
DOCUMENT_TEMPLATE_DIAGNOSTICS = TemplateDeliveryDiagnostics(
    interrupted_message="WhatsApp document delivery outcome is unknown after a provider interruption",
    rate_limited_message="Meta temporarily rate-limited this document message",
    rejected_message="Meta rejected this document template; verify the approved template and recipient details",
    accepted_without_id="WhatsApp API accepted the document without returning a message ID",
    log_event="whatsapp_document_template_rejected",
)
QR_TEMPLATE_DIAGNOSTICS = TemplateDeliveryDiagnostics(
    interrupted_message="WhatsApp QR delivery outcome is unknown after a provider interruption",
    rate_limited_message="Meta temporarily rate-limited this QR message",
    rejected_message="Meta rejected this QR template; verify the approved template and recipient details",
    accepted_without_id="WhatsApp API accepted the QR message without returning a message ID",
    log_event="whatsapp_qr_template_rejected",
)
