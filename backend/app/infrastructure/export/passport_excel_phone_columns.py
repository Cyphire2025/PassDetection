"""Identify phone columns that the single submitted-contact column replaces."""

from __future__ import annotations

import re
import unicodedata

VERIFIED_WHATSAPP_HEADER = "Verified WhatsApp Numbers"

_PHONE_WORDS = {"phone", "phones", "telephone", "tel", "mobile", "mob", "whatsapp"}
_NUMBER_WORDS = {"number", "numbers", "no", "nos", "num"}
_CONTACT_WORDS = {"contact", "contacts"}
_PHONE_QUALIFIERS = {
    "active",
    "additional",
    "alternate",
    "alternative",
    "backup",
    "business",
    "client",
    "customer",
    "emergency",
    "employee",
    "family",
    "final",
    "guardian",
    "head",
    "home",
    "member",
    "new",
    "office",
    "old",
    "parent",
    "passenger",
    "personal",
    "primary",
    "recipient",
    "registered",
    "secondary",
    "spouse",
    "staff",
    "traveler",
    "traveller",
    "upload",
    "uploaded",
    "verified",
    "work",
}
_COMPACT_ALIASES = {
    "contactnumber",
    "contactno",
    "mobilenumber",
    "mobileno",
    "phonenumber",
    "phoneno",
    "whatsappnumber",
    "whatsappno",
    "uploadphone",
    "whatsappphone",
    "clientphone",
    "familyheadphone",
    "emergencyphone",
    "verifiedwhatsappnumbers",
}


def _is_phone_label(value: str) -> bool:
    # Separate common camelCase keys before making punctuation insignificant.
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(
        r"\s*\((?:custom[ _-]+(?:detail|question)|whats[ _-]*app)(?:\s+\d+)?\)\s*$",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"whats[ _-]*app", "whatsapp", normalized, flags=re.IGNORECASE)
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", normalized)
    words = set(re.findall(r"[^\W_]+", expanded.casefold()))
    words = {word for word in words if not word.isdecimal()}
    if not words:
        return False
    if len(words) == 1 and next(iter(words)) in _COMPACT_ALIASES:
        return True
    allowed = _PHONE_WORDS | _NUMBER_WORDS | _CONTACT_WORDS | _PHONE_QUALIFIERS
    if not words <= allowed:
        return False
    return (
        bool(words & _PHONE_WORDS)
        or words <= _CONTACT_WORDS
        or bool(words & _CONTACT_WORDS and words & _NUMBER_WORDS)
    )


def is_phone_export_field(key: str, label: str) -> bool:
    """Recognize contact-number fields without treating all contact metadata as phones."""
    # ``whatsapp:department`` names the metadata source, not a phone field.
    key_name = key.partition(":")[2] if ":" in key else key
    return _is_phone_label(key_name) or _is_phone_label(label)
