"""Compose the WhatsApp HTTP surface independently of compatibility exports."""

from fastapi import APIRouter

from app.presentation.api.v1.routes.whatsapp_batch_status import router as _batch_status_router
from app.presentation.api.v1.routes.whatsapp_bulk_resend import router as _bulk_resend_router
from app.presentation.api.v1.routes.whatsapp_bulk_resend_preview import (
    router as _bulk_resend_preview_router,
)
from app.presentation.api.v1.routes.whatsapp_composer import router as _composer_router
from app.presentation.api.v1.routes.whatsapp_contact_import import router as _contact_import_router
from app.presentation.api.v1.routes.whatsapp_exports import router as _exports_router
from app.presentation.api.v1.routes.whatsapp_groups_archive import router as _groups_archive_router
from app.presentation.api.v1.routes.whatsapp_groups_delete import router as _groups_delete_router
from app.presentation.api.v1.routes.whatsapp_groups_manage import router as _groups_manage_router
from app.presentation.api.v1.routes.whatsapp_groups_read import router as _groups_read_router
from app.presentation.api.v1.routes.whatsapp_recipient_details import (
    router as _recipient_details_router,
)
from app.presentation.api.v1.routes.whatsapp_recipient_roster import (
    router as _recipient_roster_router,
)
from app.presentation.api.v1.routes.whatsapp_recipients import router as _recipients_router
from app.presentation.api.v1.routes.whatsapp_rejected_contacts import (
    router as _rejected_contacts_router,
)
from app.presentation.api.v1.routes.whatsapp_resend import router as _resend_router
from app.presentation.api.v1.routes.whatsapp_send import router as _send_router
from app.presentation.api.v1.routes.whatsapp_source_groups import router as _source_groups_router
from app.presentation.api.v1.routes.whatsapp_webhook import router as _webhook_router

router = APIRouter()
router.include_router(_webhook_router)
router.include_router(_contact_import_router)
router.include_router(_source_groups_router)
router.include_router(_groups_read_router)
router.include_router(_recipient_roster_router)
router.include_router(_exports_router)
router.include_router(_rejected_contacts_router)
router.include_router(_composer_router)
router.include_router(_groups_manage_router)
router.include_router(_recipients_router)
router.include_router(_recipient_details_router)
router.include_router(_resend_router)
router.include_router(_bulk_resend_router)
router.include_router(_bulk_resend_preview_router)
router.include_router(_groups_delete_router)
router.include_router(_groups_archive_router)
router.include_router(_send_router)
router.include_router(_batch_status_router)
