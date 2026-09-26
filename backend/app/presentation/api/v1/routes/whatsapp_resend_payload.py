"""Preserve frozen template values when publishing an explicit resend."""

from __future__ import annotations

import uuid


def resend_task_payload(
    batch_id: uuid.UUID, message_type: str, parameters: list[str], header_parameters: list[str],
) -> dict[str, object]:
    return {
        "batch_id": str(batch_id),
        "message_type": message_type,
        "message_content": (
            parameters[2] if message_type == "passport_link" else parameters[0]
        ),
        "passport_intro": parameters[0] if message_type == "passport_link" else None,
        "passport_link": parameters[1] if message_type == "passport_link" else None,
        "group_invite_link": parameters[1] if message_type == "group_invite" else None,
        "header_image_id": (header_parameters[0] if header_parameters else None),
    }
