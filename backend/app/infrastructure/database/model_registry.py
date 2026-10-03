"""Complete application metadata for migrations and database-role provisioning."""

from app.infrastructure.database import (  # noqa: F401
    ecr_models,
    email_ai_models,
    email_models,
    gc_mobile_models,
    gc_notification_models,
    mcp_artifact_models,
    mcp_communication_models,
    mcp_contact_import_models,
    mcp_document_delivery_models,
    mcp_gc_push_models,
    mcp_models,
    mcp_native_transfer_models,
    mcp_operation_models,
    mcp_record_revision_models,
    mcp_whatsapp_media_models,
    menu_models,
    models,
    my_photos_models,
    passport_ecr_models,
    passport_image_library_model,
    whatsapp_send_intent_models,
)
from app.infrastructure.database.model_base import Base as Base
