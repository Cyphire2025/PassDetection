"""Compatibility entry point for the current Meta WhatsApp provider contracts."""

from app.infrastructure.whatsapp.provider_errors import (
    WhatsAppCloudApiError as WhatsAppCloudApiError,
)
from app.infrastructure.whatsapp.provider_errors import (
    _meta_code as _meta_code,
)
from app.infrastructure.whatsapp.provider_errors import (
    _meta_error_reference as _meta_error_reference,
)
from app.infrastructure.whatsapp.provider_media import (
    WHATSAPP_MAX_DOCUMENT_BYTES as WHATSAPP_MAX_DOCUMENT_BYTES,
)
from app.infrastructure.whatsapp.provider_media import (
    WHATSAPP_PDF_CONTENT_TYPE as WHATSAPP_PDF_CONTENT_TYPE,
)
from app.infrastructure.whatsapp.provider_media import (
    upload_whatsapp_document as upload_whatsapp_document,
)
from app.infrastructure.whatsapp.provider_media import (
    upload_whatsapp_image as upload_whatsapp_image,
)
from app.infrastructure.whatsapp.provider_messages import (
    send_whatsapp_authentication_template as send_whatsapp_authentication_template,
)
from app.infrastructure.whatsapp.provider_messages import (
    send_whatsapp_document_template as send_whatsapp_document_template,
)
from app.infrastructure.whatsapp.provider_messages import (
    send_whatsapp_document_update_template as send_whatsapp_document_update_template,
)
from app.infrastructure.whatsapp.provider_messages import (
    send_whatsapp_qr_template as send_whatsapp_qr_template,
)
from app.infrastructure.whatsapp.provider_messages import (
    send_whatsapp_template as send_whatsapp_template,
)
from app.infrastructure.whatsapp.provider_payloads import (
    _document_parameter as _document_parameter,
)
from app.infrastructure.whatsapp.provider_payloads import (
    _image_parameter as _image_parameter,
)
from app.infrastructure.whatsapp.provider_payloads import (
    _text_parameter as _text_parameter,
)
from app.infrastructure.whatsapp.provider_transport import (
    _send_whatsapp_template_payload as _send_whatsapp_template_payload,
)
from app.infrastructure.whatsapp.provider_transport import (
    logger as logger,
)
