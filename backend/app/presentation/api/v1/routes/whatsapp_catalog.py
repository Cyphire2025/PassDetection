"""A message catalogue describes shared forms instead of growing action menus."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.domain.entities.entities import User
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES
from app.presentation.dependencies.auth import require_role

router = APIRouter()


class ComposerField(BaseModel):
    key: Literal["message_content", "passport_intro", "passport_link", "group_invite_link"]
    label: str
    kind: Literal["textarea", "url", "text"] = "textarea"
    required: bool = True
    max_length: int = 600


class MessageDefinition(BaseModel):
    id: str
    message_type: WhatsAppMessageType
    label: str
    description: str
    category: str
    image_required: bool = False
    audience: Literal["standard", "reminder", "update"] = "standard"
    repeatable: bool = False
    fields: list[ComposerField]


MESSAGE_CATALOG = (
    MessageDefinition(
        id="text_update",
        message_type="update",
        label="Text trip update",
        description="Write a text update and filter recipients by submission and document delivery.",
        category="Trip updates",
        audience="update",
        repeatable=True,
        fields=[ComposerField(key="message_content", label="Update message")],
    ),
    MessageDefinition(
        id="welcome",
        message_type="welcome",
        label="Welcome message",
        description="Introduce the trip and welcome new recipients.",
        category="Getting started",
        image_required=True,
        fields=[ComposerField(key="message_content", label="Welcome message")],
    ),
    MessageDefinition(
        id="passport_link",
        message_type="passport_link",
        label="Passport link",
        description="Share the document upload link and instructions.",
        category="Documents",
        image_required=True,
        fields=[
            ComposerField(
                key="passport_link", label="Passport upload link", kind="url", max_length=2048
            ),
            ComposerField(key="passport_intro", label="Introduction"),
            ComposerField(key="message_content", label="Instructions"),
        ],
    ),
    MessageDefinition(
        id="reminder",
        message_type="reminder",
        label="Reminder",
        description="Follow up with everyone or only people who have not submitted.",
        category="Follow-ups",
        audience="reminder",
        repeatable=True,
        fields=[ComposerField(key="message_content", label="Reminder message")],
    ),
    MessageDefinition(
        id="group_invite",
        message_type="group_invite",
        label="Group invitation",
        description="Invite recipients to the official WhatsApp group.",
        category="Getting started",
        image_required=True,
        fields=[
            ComposerField(
                key="group_invite_link",
                label="WhatsApp group invite link",
                kind="url",
                max_length=2048,
            ),
            ComposerField(key="message_content", label="Invitation message"),
        ],
    ),
    MessageDefinition(
        id="update",
        message_type="update",
        label="Trip update",
        description="Send an update using submission and document delivery filters.",
        category="Trip updates",
        audience="update",
        repeatable=True,
        fields=[ComposerField(key="message_content", label="Update message")],
    ),
)


@router.get("/message-catalog", response_model=list[MessageDefinition])
async def message_catalog(
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
) -> list[MessageDefinition]:
    return list(MESSAGE_CATALOG)
