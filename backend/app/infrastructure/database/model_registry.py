"""Complete application metadata for migrations and database-role provisioning."""

from app.infrastructure.database import (  # noqa: F401
    ecr_models,
    email_ai_models,
    email_models,
    gc_mobile_models,
    gc_notification_models,
    menu_models,
    models,
    my_photos_models,
    passport_ecr_models,
    passport_image_library_model,
)
from app.infrastructure.database.model_base import Base as Base
