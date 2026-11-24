"""Prepare legacy annotation and default globals before private model registration.

Importing the public module object supports facade-first and owner-first loads.
Owners use only predeclared helpers, never partially initialized class exports.
"""

from app.infrastructure.database import email_models as _legacy_models  # noqa: F401
