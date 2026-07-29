"""Render stored attendance QR payloads as WhatsApp-ready PNG images."""

from __future__ import annotations

import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def render_attendance_qr_png(payload: str) -> bytes:
    normalized = payload.strip()
    if not normalized.startswith("pdatt:") or len(normalized) > 64:
        raise ValueError("Attendance QR payload is invalid")

    code = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=12,
        border=4,
    )
    code.add_data(normalized)
    code.make(fit=True)
    image = code.make_image(fill_color="#020617", back_color="#ffffff")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
