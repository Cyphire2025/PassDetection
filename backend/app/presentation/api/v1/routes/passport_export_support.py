"""Stable compatibility imports for focused passport export support owners."""

from __future__ import annotations

import uuid as uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow as SubmissionMatchRow,
)
from app.domain.entities.entities import PassportSubmission
from app.domain.value_objects import passport_export_history as history_values
from app.presentation.api.v1.routes.passport_export_agency_matches import (
    _AGENCY_MATCH_SIMILARITY_THRESHOLD as _AGENCY_MATCH_SIMILARITY_THRESHOLD,
)
from app.presentation.api.v1.routes.passport_export_agency_matches import (
    _agency_match_similarity as _agency_match_similarity,
)
from app.presentation.api.v1.routes.passport_export_agency_matches import (
    _AgencyExportMatches as _AgencyExportMatches,
)
from app.presentation.api.v1.routes.passport_export_agency_matches import (
    _apply_agency_export_matches as _apply_agency_export_matches,
)
from app.presentation.api.v1.routes.passport_export_agency_matches import (
    _export_agency_matches as _export_agency_matches,
)
from app.presentation.api.v1.routes.passport_export_agency_matches import (
    _export_effective_whatsapp_matches as _export_effective_whatsapp_matches,
)
from app.presentation.api.v1.routes.passport_export_agency_matches import (
    _normalized_agency_match_value as _normalized_agency_match_value,
)
from app.presentation.api.v1.routes.passport_export_agency_matches import (
    _submission_agency_dealership_name as _submission_agency_dealership_name,
)
from app.presentation.api.v1.routes.passport_export_catalog import (
    _FIXED_IMPORTED_EXPORT_KEYS as _FIXED_IMPORTED_EXPORT_KEYS,
)
from app.presentation.api.v1.routes.passport_export_catalog import (
    _WHATSAPP_SOURCE_METADATA_KEYS as _WHATSAPP_SOURCE_METADATA_KEYS,
)
from app.presentation.api.v1.routes.passport_export_catalog import (
    _ZONE_IMPORTED_KEYS as _ZONE_IMPORTED_KEYS,
)
from app.presentation.api.v1.routes.passport_export_catalog import (
    _agency_match_export_field as _agency_match_export_field,
)
from app.presentation.api.v1.routes.passport_export_catalog import (
    _combined_export_field_catalog as _combined_export_field_catalog,
)
from app.presentation.api.v1.routes.passport_export_catalog import (
    _export_additional_values as _export_additional_values,
)
from app.presentation.api.v1.routes.passport_export_catalog import (
    _export_agency_match_field_catalog as _export_agency_match_field_catalog,
)
from app.presentation.api.v1.routes.passport_export_catalog import (
    _export_field_catalog as _export_field_catalog,
)
from app.presentation.api.v1.routes.passport_export_catalog import (
    _merge_export_field_catalogs as _merge_export_field_catalogs,
)
from app.presentation.api.v1.routes.passport_export_match_sources import (
    _export_whatsapp_match_rows as _export_whatsapp_match_rows,
)
from app.presentation.api.v1.routes.passport_export_metadata import (
    _export_group_details as _export_group_details,
)
from app.presentation.api.v1.routes.passport_export_metadata import (
    _export_people_snapshot as _export_people_snapshot,
)
from app.presentation.api.v1.routes.passport_export_metadata import (
    _group_export_details as _group_export_details,
)
from app.presentation.api.v1.routes.passport_export_metadata import (
    _international_airport_is_enabled as _international_airport_is_enabled,
)
from app.presentation.api.v1.routes.passport_export_pending_rows import (
    _apply_pending_export_fields as _apply_pending_export_fields,
)
from app.presentation.api.v1.routes.passport_export_pending_rows import (
    _pending_recipient_export_rows as _pending_recipient_export_rows,
)
from app.presentation.api.v1.routes.passport_export_recipient_values import (
    _WHATSAPP_EMAIL_IMPORTED_KEYS as _WHATSAPP_EMAIL_IMPORTED_KEYS,
)
from app.presentation.api.v1.routes.passport_export_recipient_values import (
    _WHATSAPP_PHONE_IMPORTED_KEYS as _WHATSAPP_PHONE_IMPORTED_KEYS,
)
from app.presentation.api.v1.routes.passport_export_recipient_values import (
    _export_whatsapp_contacts as _export_whatsapp_contacts,
)
from app.presentation.api.v1.routes.passport_export_recipient_values import (
    _export_zone_names_from_match_rows as _export_zone_names_from_match_rows,
)
from app.presentation.api.v1.routes.passport_export_recipient_values import (
    _imported_zone_name as _imported_zone_name,
)
from app.presentation.api.v1.routes.passport_export_recipient_values import (
    _normalized_imported_field_key as _normalized_imported_field_key,
)
from app.presentation.api.v1.routes.passport_export_recipient_values import (
    _recipient_export_value as _recipient_export_value,
)
from app.presentation.api.v1.routes.passport_export_recipient_values import (
    _recipient_old_given_name as _recipient_old_given_name,
)
from app.presentation.api.v1.routes.passport_export_tracking_rows import (
    _select_whatsapp_tracking_export_payload as _select_whatsapp_tracking_export_payload,
)
from app.presentation.api.v1.routes.passport_export_tracking_rows import (
    _stored_resolution_uuid_list as _stored_resolution_uuid_list,
)
from app.presentation.api.v1.routes.passport_export_tracking_rows import (
    _whatsapp_tracking_export_rows as _whatsapp_tracking_export_rows,
)

_validated_export_history_ids = history_values.validated_export_history_ids
_validated_export_history_people = history_values.validated_export_history_people
_validated_export_kind = history_values.validated_export_kind
_validated_export_mode = history_values.validated_export_mode


async def _export_zone_names(
    session: AsyncSession,
    submissions: list[PassportSubmission],
) -> dict[uuid.UUID, str]:
    """Resolve exact imported WhatsApp zones using the production matcher."""

    rows_by_group = await _export_whatsapp_match_rows(session, submissions)
    return _export_zone_names_from_match_rows(submissions, rows_by_group)
