"""Stable review-support aliases and small shared route policies."""

from __future__ import annotations

import json as json
import re as re
import uuid as uuid
from dataclasses import dataclass as dataclass
from datetime import date as date
from datetime import datetime as datetime
from typing import Literal as Literal

from app.domain.entities.entities import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES as OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
)
from app.domain.entities.entities import (
    PassportSubmission as PassportSubmission,
)
from app.domain.entities.entities import (
    User as User,
)
from app.domain.entities.entities import (
    UserRole as UserRole,
)
from app.infrastructure.database.models import (
    ClientGroupModel as ClientGroupModel,
)
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel as ClientGroupWhatsAppBroadcastLinkModel,
)
from app.infrastructure.database.models import (
    DistributedDocumentModel as DistributedDocumentModel,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel as WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel as WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.export.document_assignment_excel_exporter import (
    DocumentAssignmentExportRow as DocumentAssignmentExportRow,
)
from app.presentation.api.v1.routes.document_distribution_review_export import (
    _SENT_DOCUMENT_STATUSES as _SENT_DOCUMENT_STATUSES,
)
from app.presentation.api.v1.routes.document_distribution_review_export import (
    DocumentAssignmentExportFilter as DocumentAssignmentExportFilter,
)
from app.presentation.api.v1.routes.document_distribution_review_export import (
    _document_assignment_export_rows as _document_assignment_export_rows,
)
from app.presentation.api.v1.routes.document_distribution_review_export import (
    _joined_document_values as _joined_document_values,
)
from app.presentation.api.v1.routes.document_distribution_review_projection import (
    _passenger_review_rows as _passenger_review_rows,
)
from app.presentation.api.v1.routes.document_distribution_review_projection import (
    _passport_number as _passport_number,
)
from app.presentation.api.v1.routes.document_distribution_review_projection import (
    _physical_file_accounting as _physical_file_accounting,
)
from app.presentation.api.v1.routes.document_distribution_review_snapshots import (
    _document_match_roster_snapshot as _document_match_roster_snapshot,
)
from app.presentation.api.v1.routes.document_distribution_review_snapshots import (
    _linked_document_match_source_from_models as _linked_document_match_source_from_models,
)
from app.presentation.api.v1.routes.document_distribution_review_snapshots import (
    _LinkedDocumentMatchSource as _LinkedDocumentMatchSource,
)
from app.presentation.api.v1.routes.document_distribution_review_snapshots import (
    _snapshot_value as _snapshot_value,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DistributedDocumentResponse as DistributedDocumentResponse,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentAssignmentIssueResponse as DocumentAssignmentIssueResponse,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentPassengerReviewRow as DocumentPassengerReviewRow,
)


def _owner_scope_for(user: User) -> uuid.UUID | None:
    return user.id if user.role == UserRole.AGENCY_STAFF else None


def _submitted_statuses() -> tuple[str, ...]:
    return OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES


def _safe_filename(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())[:120]
    return name or "document.pdf"
