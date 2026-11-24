"""Prepare the existing ORM annotation namespace before loading focused owners.

Facade-first and direct owner-first imports share the original module globals;
owners never consume incomplete class exports during initialization.
"""

from app.infrastructure.database import communications_models as _legacy_models  # noqa: F401
