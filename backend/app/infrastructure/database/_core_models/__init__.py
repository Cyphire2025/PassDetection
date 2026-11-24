"""Prepare legacy annotation globals before registering private model owners.

Mapped classes retain their published module identity. Importing the public
module object here supports both facade-first and owner-first initialization;
private owners never consume partially initialized class exports.
"""

from app.infrastructure.database import models as _legacy_models  # noqa: F401
