"""Keep archived broadcast lists readable while preventing further mutations."""

from fastapi import HTTPException, status

from app.infrastructure.database.models import WhatsAppBroadcastGroupModel


def require_active_broadcast(group: WhatsAppBroadcastGroupModel) -> None:
    if getattr(group, "archived_at", None) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This WhatsApp broadcast is archived. Restore it before making changes or sending messages.",
        )
