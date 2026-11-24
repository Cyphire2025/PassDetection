"""Initialize the legacy annotation namespace before focused GC model owners.

Facade-first and direct owner-first imports register the same classes in their
original module namespace and order; owners consume no incomplete class exports.
"""

from app.infrastructure.database import gc_mobile_models as _legacy_models  # noqa: F401
