"""Prepare the legacy ORM annotation namespace before focused owners load.

Both facade-first and direct owner imports initialize the same original class
namespace before SQLAlchemy resolves postponed mapped annotations.
"""

from app.infrastructure.database import document_models as _legacy_models  # noqa: F401
