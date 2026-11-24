"""Compatibility imports for WhatsApp contact rules and response projections."""

from __future__ import annotations

from app.presentation.api.v1.routes.whatsapp_contact_excel import (
    _bounded_excel_raw_value as _bounded_excel_raw_value,
)
from app.presentation.api.v1.routes.whatsapp_contact_excel import (
    _excel_fields_from_row as _excel_fields_from_row,
)
from app.presentation.api.v1.routes.whatsapp_contact_excel import (
    _excel_header_columns as _excel_header_columns,
)
from app.presentation.api.v1.routes.whatsapp_contact_excel import (
    _excel_name_from_row as _excel_name_from_row,
)
from app.presentation.api.v1.routes.whatsapp_contact_excel import (
    _excel_raw_name_from_row as _excel_raw_name_from_row,
)
from app.presentation.api.v1.routes.whatsapp_contact_excel import (
    _find_excel_contact_header as _find_excel_contact_header,
)
from app.presentation.api.v1.routes.whatsapp_contact_excel import (
    _is_excel_name_header as _is_excel_name_header,
)
from app.presentation.api.v1.routes.whatsapp_contact_excel import (
    _is_excel_phone_header as _is_excel_phone_header,
)
from app.presentation.api.v1.routes.whatsapp_contact_excel import (
    _is_repeated_excel_header as _is_repeated_excel_header,
)
from app.presentation.api.v1.routes.whatsapp_contact_excel import (
    _row_has_contact_identity as _row_has_contact_identity,
)
from app.presentation.api.v1.routes.whatsapp_contact_parse_result import (
    _WhatsAppExcelContactParseResult as _WhatsAppExcelContactParseResult,
)
from app.presentation.api.v1.routes.whatsapp_contact_rejections import (
    _add_rejected_contact_models as _add_rejected_contact_models,
)
from app.presentation.api.v1.routes.whatsapp_contact_rejections import (
    _parse_rejected_contacts as _parse_rejected_contacts,
)
from app.presentation.api.v1.routes.whatsapp_contact_rejections import (
    _rejected_contact_fingerprint as _rejected_contact_fingerprint,
)
from app.presentation.api.v1.routes.whatsapp_contact_responses import (
    _excel_contact_preview_response as _excel_contact_preview_response,
)
from app.presentation.api.v1.routes.whatsapp_contact_responses import (
    _recipient_response as _recipient_response,
)
from app.presentation.api.v1.routes.whatsapp_contact_responses import (
    _rejected_contact_response as _rejected_contact_response,
)
from app.presentation.api.v1.routes.whatsapp_contact_responses import (
    _support_contact_response as _support_contact_response,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _EMPTY_EXCEL_VALUES as _EMPTY_EXCEL_VALUES,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _EXCEL_FIELD_ALIASES as _EXCEL_FIELD_ALIASES,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _MATCHING_FIELD_LABELS as _MATCHING_FIELD_LABELS,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _WHATSAPP_CONTACT_REJECTION_REASONS as _WHATSAPP_CONTACT_REJECTION_REASONS,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_EXCEL_ARCHIVE_MEMBERS as MAX_WHATSAPP_EXCEL_ARCHIVE_MEMBERS,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_EXCEL_COMPRESSION_RATIO as MAX_WHATSAPP_EXCEL_COMPRESSION_RATIO,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS as MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_EXCEL_ROWS as MAX_WHATSAPP_EXCEL_ROWS,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_EXCEL_UNCOMPRESSED_BYTES as MAX_WHATSAPP_EXCEL_UNCOMPRESSED_BYTES,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_IMPORTED_FIELD_KEY_LENGTH as MAX_WHATSAPP_IMPORTED_FIELD_KEY_LENGTH,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH as MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_IMPORTED_FIELDS as MAX_WHATSAPP_IMPORTED_FIELDS,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_IMPORTED_FIELDS_BYTES as MAX_WHATSAPP_IMPORTED_FIELDS_BYTES,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP as MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_REJECTED_ROWS as MAX_WHATSAPP_REJECTED_ROWS,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import PHONE_RE as PHONE_RE
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    WHATSAPP_NON_MATCHING_IMPORTED_FIELDS as WHATSAPP_NON_MATCHING_IMPORTED_FIELDS,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    WHATSAPP_ROSTER_SOURCE_FIELDS as WHATSAPP_ROSTER_SOURCE_FIELDS,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    WHATSAPP_UPLOAD_READ_CHUNK_BYTES as WHATSAPP_UPLOAD_READ_CHUNK_BYTES,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import _clean_name as _clean_name
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _clean_required_name as _clean_required_name,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _excel_cell_text as _excel_cell_text,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _excel_field_key as _excel_field_key,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _excel_header_label as _excel_header_label,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _normalize_phone as _normalize_phone,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _validate_excel_archive as _validate_excel_archive,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    _validated_rejection_code as _validated_rejection_code,
)
from app.presentation.api.v1.routes.whatsapp_imported_fields import (
    _imported_field_keys_for_contacts as _imported_field_keys_for_contacts,
)
from app.presentation.api.v1.routes.whatsapp_imported_fields import (
    _matching_field_label as _matching_field_label,
)
from app.presentation.api.v1.routes.whatsapp_imported_fields import (
    _matching_field_options as _matching_field_options,
)
from app.presentation.api.v1.routes.whatsapp_imported_fields import (
    _merge_imported_field_keys as _merge_imported_field_keys,
)
from app.presentation.api.v1.routes.whatsapp_imported_fields import (
    _parse_imported_field_keys as _parse_imported_field_keys,
)
from app.presentation.api.v1.routes.whatsapp_imported_fields import (
    _safe_imported_fields as _safe_imported_fields,
)
from app.presentation.api.v1.routes.whatsapp_recipient_inputs import (
    _activate_recipient_models as _activate_recipient_models,
)
from app.presentation.api.v1.routes.whatsapp_recipient_inputs import (
    _merge_recipient_inputs as _merge_recipient_inputs,
)
from app.presentation.api.v1.routes.whatsapp_recipient_inputs import (
    _normalized_recipient_inputs as _normalized_recipient_inputs,
)
from app.presentation.api.v1.routes.whatsapp_recipient_inputs import (
    _parse_manual_contacts as _parse_manual_contacts,
)
from app.presentation.api.v1.routes.whatsapp_recipient_inputs import (
    _parse_support_contacts as _parse_support_contacts,
)
from app.presentation.api.v1.routes.whatsapp_roster_order import (
    _new_roster_display_orders as _new_roster_display_orders,
)
from app.presentation.api.v1.routes.whatsapp_roster_order import (
    _next_roster_display_order as _next_roster_display_order,
)
from app.presentation.api.v1.routes.whatsapp_roster_order import _positive_int as _positive_int
from app.presentation.api.v1.routes.whatsapp_roster_order import (
    _roster_source_sort_key as _roster_source_sort_key,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppContactPreviewRejectedRow as WhatsAppContactPreviewRejectedRow,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppContactRejectionCode as WhatsAppContactRejectionCode,
)

# Keep forward annotation resolution for the legacy parse-result module identity.
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppRecipientInput as WhatsAppRecipientInput,
)
