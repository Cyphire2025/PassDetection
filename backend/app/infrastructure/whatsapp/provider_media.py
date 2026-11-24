"""Validated image and PDF media uploads, separate from message submission."""

from __future__ import annotations

import logging

import httpx

from app.core.config.settings import Settings
from app.infrastructure.whatsapp.provider_errors import WhatsAppCloudApiError, _meta_error_reference

logger = logging.getLogger("app.infrastructure.whatsapp.cloud_api_provider")
WHATSAPP_PDF_CONTENT_TYPE = "application/pdf"
WHATSAPP_MAX_DOCUMENT_BYTES = 100 * 1024 * 1024


async def upload_whatsapp_image(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    file_name: str,
    file_content: bytes,
    content_type: str,
) -> str:
    """Upload a validated image to Meta and return its reusable media ID."""

    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise WhatsAppCloudApiError(
            "WhatsApp Cloud API credentials are incomplete",
            code="WHATSAPP_PROVIDER_NOT_CONFIGURED",
        )

    try:
        response = await client.post(
            (
                f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
                f"{settings.whatsapp_phone_number_id}/media"
            ),
            data={
                "messaging_product": "whatsapp",
                "type": content_type,
            },
            files={
                "file": (
                    file_name,
                    file_content,
                    content_type,
                ),
            },
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
        )
    except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout) as exc:
        raise WhatsAppCloudApiError(
            "The image could not be uploaded to WhatsApp",
            code="WHATSAPP_MEDIA_UPLOAD_UNREACHABLE",
            transient=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise WhatsAppCloudApiError(
            "The image upload was interrupted",
            code="WHATSAPP_MEDIA_UPLOAD_INTERRUPTED",
            transient=True,
        ) from exc

    try:
        data = response.json()
    except ValueError:
        data = {}
    media_id = data.get("id") if isinstance(data, dict) else None
    if response.status_code >= 400 or not isinstance(media_id, str) or not media_id.strip():
        logger.warning(
            "whatsapp_media_upload_rejected",
            extra={"status_code": response.status_code},
        )
        raise WhatsAppCloudApiError(
            "Meta rejected the image; use a clear JPEG or PNG and try again",
            code="WHATSAPP_MEDIA_UPLOAD_REJECTED",
            transient=response.status_code == 429 or response.status_code >= 500,
        )
    return media_id.strip()


async def upload_whatsapp_document(
    *,
    client: httpx.AsyncClient,
    settings: Settings,
    file_name: str,
    file_content: bytes,
    content_type: str,
) -> str:
    """Upload one private travel document to Meta for a template header."""

    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise WhatsAppCloudApiError(
            "WhatsApp Cloud API credentials are incomplete",
            code="WHATSAPP_PROVIDER_NOT_CONFIGURED",
        )
    if not file_content.startswith(b"%PDF-") or len(file_content) > WHATSAPP_MAX_DOCUMENT_BYTES:
        raise WhatsAppCloudApiError(
            "The saved travel document is not a valid supported PDF",
            code="WHATSAPP_DOCUMENT_INVALID",
        )
    normalized_filename = file_name.strip() or "travel-document.pdf"
    if not normalized_filename.lower().endswith(".pdf"):
        normalized_filename = f"{normalized_filename}.pdf"
    try:
        response = await client.post(
            (
                f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
                f"{settings.whatsapp_phone_number_id}/media"
            ),
            data={"messaging_product": "whatsapp"},
            files={
                "file": (
                    normalized_filename,
                    file_content,
                    WHATSAPP_PDF_CONTENT_TYPE,
                )
            },
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
        )
    except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout) as exc:
        raise WhatsAppCloudApiError(
            "The travel document could not be uploaded to WhatsApp",
            code="WHATSAPP_DOCUMENT_UPLOAD_UNREACHABLE",
            transient=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise WhatsAppCloudApiError(
            "The travel document upload was interrupted",
            code="WHATSAPP_DOCUMENT_UPLOAD_INTERRUPTED",
            transient=True,
        ) from exc

    try:
        data = response.json()
    except ValueError:
        data = {}
    media_id = data.get("id") if isinstance(data, dict) else None
    if response.status_code >= 400 or not isinstance(media_id, str) or not media_id.strip():
        meta_code, meta_subcode, meta_reference = _meta_error_reference(data)
        logger.warning(
            "whatsapp_document_upload_rejected",
            extra={
                "status_code": response.status_code,
                "meta_code": meta_code,
                "meta_subcode": meta_subcode,
            },
        )
        raise WhatsAppCloudApiError(
            "Meta rejected the travel document upload"
            f"{meta_reference}; verify the PDF and try again",
            code="WHATSAPP_DOCUMENT_UPLOAD_REJECTED",
            transient=response.status_code == 429 or response.status_code >= 500,
        )
    return media_id.strip()
