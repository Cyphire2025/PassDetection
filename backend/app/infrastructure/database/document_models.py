"""Stable document model imports with original ORM registration order."""

from __future__ import annotations

import uuid as uuid
from datetime import datetime as datetime

from sqlalchemy import BigInteger as BigInteger
from sqlalchemy import CheckConstraint as CheckConstraint
from sqlalchemy import DateTime as DateTime
from sqlalchemy import Float as Float
from sqlalchemy import ForeignKey as ForeignKey
from sqlalchemy import Index as Index
from sqlalchemy import Integer as Integer
from sqlalchemy import LargeBinary as LargeBinary
from sqlalchemy import String as String
from sqlalchemy import Text as Text
from sqlalchemy import UniqueConstraint as UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as UUID
from sqlalchemy.orm import Mapped as Mapped
from sqlalchemy.orm import mapped_column as mapped_column

from app.infrastructure.database.model_base import JSONB as JSONB
from app.infrastructure.database.model_base import Base as Base
from app.infrastructure.database.model_base import _utcnow as _utcnow

# Preserve class/table registration order and the qualified ORM namespace.
# isort: off
from ._document_models.distribution import (
    DocumentDistributionBatchModel as DocumentDistributionBatchModel,
    DistributedDocumentModel as DistributedDocumentModel,
)
from ._document_models.delivery import (
    DocumentWhatsAppDeliveryModel as DocumentWhatsAppDeliveryModel,
)
from ._document_models.upload_scan import (
    UntrustedUploadScanModel as UntrustedUploadScanModel,
)
from ._document_models.rename import (
    DocumentRenameBatchModel as DocumentRenameBatchModel,
    DocumentRenameItemModel as DocumentRenameItemModel,
)
from ._document_models.upload_chunk import (
    DocumentUploadChunkModel as DocumentUploadChunkModel,
)
from ._document_models.cleanup import (
    StorageCleanupJobModel as StorageCleanupJobModel,
)
# isort: on
