"""Stable imports for current roster acquisition and response projections."""

from __future__ import annotations

import asyncio as asyncio
import re as re
import uuid as uuid
from collections.abc import Mapping as Mapping
from collections.abc import Sequence as Sequence
from math import ceil as ceil
from typing import Literal as Literal
from typing import Protocol as Protocol
from typing import cast as cast

from sqlalchemy import or_ as or_
from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import (
    normalize_whatsapp_phone as normalize_whatsapp_phone,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientFieldSet as RecipientFieldSet,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow as SubmissionMatchRow,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchSummary as SubmissionMatchSummary,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    compare_group_submissions as compare_group_submissions,
)
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES as OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
)
from app.infrastructure.database.models import (
    PassportRosterResolutionModel as PassportRosterResolutionModel,
)
from app.infrastructure.database.models import PassportSubmissionModel as PassportSubmissionModel
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel as WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    recipient_comparison_from_model as recipient_comparison_from_model,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    submission_comparison_from_model as submission_comparison_from_model,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_acquisition import (
    _ClientGroupScope as _ClientGroupScope,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_acquisition import (
    load_current_whatsapp_match_rows as load_current_whatsapp_match_rows,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_resolutions import (
    include_active_resolution_rows as include_active_resolution_rows,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_resolutions import (
    stored_uuid_list as stored_uuid_list,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    _MatchConfidence as _MatchConfidence,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    _MatchEvidenceKind as _MatchEvidenceKind,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    _MatchStatus as _MatchStatus,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    _RosterResolutionStatus as _RosterResolutionStatus,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    _RosterResolutionType as _RosterResolutionType,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    _validated_match_confidence as _validated_match_confidence,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    _validated_match_evidence_kind as _validated_match_evidence_kind,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    _validated_match_status as _validated_match_status,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    _validated_roster_resolution_status as _validated_roster_resolution_status,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    _validated_roster_resolution_type as _validated_roster_resolution_type,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    build_whatsapp_matches_response as build_whatsapp_matches_response,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    roster_resolution_response as roster_resolution_response,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_responses import (
    submission_detail_response as submission_detail_response,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    ClientGroupWhatsAppMatchesResponse as ClientGroupWhatsAppMatchesResponse,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    PassportRosterResolutionResponse as PassportRosterResolutionResponse,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    WhatsAppRecipientImportedFieldsResponse as WhatsAppRecipientImportedFieldsResponse,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    WhatsAppSubmissionDetailResponse as WhatsAppSubmissionDetailResponse,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    WhatsAppSubmissionMatchCountsResponse as WhatsAppSubmissionMatchCountsResponse,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    WhatsAppSubmissionMatchEvidenceResponse as WhatsAppSubmissionMatchEvidenceResponse,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    WhatsAppSubmissionMatchRowResponse as WhatsAppSubmissionMatchRowResponse,
)
