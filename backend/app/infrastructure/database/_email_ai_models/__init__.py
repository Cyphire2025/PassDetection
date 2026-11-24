"""Initialize legacy defaults before registering focused AI model owners.

The public facade defines shared callbacks before these imports. Loading an
owner first uses the same ordered bootstrap and never registers duplicate tables.
"""

from app.infrastructure.database import email_ai_models as _legacy_models  # noqa: F401
