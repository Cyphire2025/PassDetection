"""Deterministic identity comparison for WhatsApp recipients and submissions.

Exact contact and identifier evidence can assign a submission automatically.
Names remain useful evidence, but a name alone never creates an automatic
match under the legacy policy. Explicit per-link field selections are an
operator-authored policy: an exact normalized match on *any* selected field is
strong evidence. A submission is assigned to at most one logical recipient;
collisions and contradictory evidence are surfaced for staff review.
"""

from __future__ import annotations

from app.application.use_cases.whatsapp.group_match_coordinator import (
    compare_group_submissions as compare_group_submissions,
)
from app.application.use_cases.whatsapp.group_match_evidence import (
    _candidate_submission_indexes as _candidate_submission_indexes,
)
from app.application.use_cases.whatsapp.group_match_evidence import (
    _duplicate_submission_ids as _duplicate_submission_ids,
)
from app.application.use_cases.whatsapp.group_match_evidence import (
    _evidence_item as _evidence_item,
)
from app.application.use_cases.whatsapp.group_match_evidence import (
    _pair_evidence as _pair_evidence,
)
from app.application.use_cases.whatsapp.group_match_evidence import (
    _same_identity_basis as _same_identity_basis,
)
from app.application.use_cases.whatsapp.group_match_evidence import (
    _submission_evidence_indexes as _submission_evidence_indexes,
)
from app.application.use_cases.whatsapp.group_match_evidence import (
    _unique_compound_names as _unique_compound_names,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _EMAIL_KEYS as _EMAIL_KEYS,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _GIVEN_NAME_KEYS as _GIVEN_NAME_KEYS,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _MATCH_DATE_FIELD_KEYS as _MATCH_DATE_FIELD_KEYS,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _MATCH_FIELD_KEY_ALIASES as _MATCH_FIELD_KEY_ALIASES,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _MATCH_IDENTIFIER_FIELD_KEYS as _MATCH_IDENTIFIER_FIELD_KEYS,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _MISSING_MATCH_VALUES as _MISSING_MATCH_VALUES,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _NAME_EVIDENCE_WEIGHT as _NAME_EVIDENCE_WEIGHT,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _NAME_KEYS as _NAME_KEYS,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _PASSPORT_KEYS as _PASSPORT_KEYS,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _PHONE_KEYS as _PHONE_KEYS,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _PRIVATE_SELECTED_FIELD_KEYS as _PRIVATE_SELECTED_FIELD_KEYS,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _SELECTED_FIELD_EVIDENCE_WEIGHT as _SELECTED_FIELD_EVIDENCE_WEIGHT,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _STAFF_CODE_KEYS as _STAFF_CODE_KEYS,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _STRONG_EVIDENCE_WEIGHTS as _STRONG_EVIDENCE_WEIGHTS,
)
from app.application.use_cases.whatsapp.group_match_fields import (
    _SURNAME_KEYS as _SURNAME_KEYS,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _mapping_field_values as _mapping_field_values,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _mapping_values as _mapping_values,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _MappingValue as _MappingValue,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _normalized_date as _normalized_date,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _normalized_email as _normalized_email,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _normalized_generic as _normalized_generic,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _normalized_identifier as _normalized_identifier,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _normalized_key as _normalized_key,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _normalized_name as _normalized_name,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _normalized_phone as _normalized_phone,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _normalized_values as _normalized_values,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _NormalizedInput as _NormalizedInput,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    _selected_field_normalizer as _selected_field_normalizer,
)
from app.application.use_cases.whatsapp.group_match_normalization import (
    normalize_matching_field_key as normalize_matching_field_key,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    _composed_names as _composed_names,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    _logical_recipients as _logical_recipients,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    _passport_fields as _passport_fields,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    _recipient_profile as _recipient_profile,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    _recipient_sort_key as _recipient_sort_key,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    _submission_field_map as _submission_field_map,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    _submission_profile as _submission_profile,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    _submission_sort_key as _submission_sort_key,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    _timestamp_key as _timestamp_key,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    recipient_identity_evidence as recipient_identity_evidence,
)
from app.application.use_cases.whatsapp.group_match_profiles import (
    submission_identity_evidence as submission_identity_evidence,
)
from app.application.use_cases.whatsapp.group_match_rows import (
    _recipient_row as _recipient_row,
)
from app.application.use_cases.whatsapp.group_match_rows import (
    _row_shared_fields as _row_shared_fields,
)
from app.application.use_cases.whatsapp.group_match_rows import (
    _unmatched_submission_row as _unmatched_submission_row,
)
from app.application.use_cases.whatsapp.group_match_rows import (
    filter_and_sort_match_rows as filter_and_sort_match_rows,
)
from app.application.use_cases.whatsapp.group_match_rows import (
    summarize_match_rows as summarize_match_rows,
)
from app.application.use_cases.whatsapp.group_match_types import (
    IdentityEvidenceValues as IdentityEvidenceValues,
)
from app.application.use_cases.whatsapp.group_match_types import (
    MatchEvidence as MatchEvidence,
)
from app.application.use_cases.whatsapp.group_match_types import (
    RecipientFieldSet as RecipientFieldSet,
)
from app.application.use_cases.whatsapp.group_match_types import (
    RecipientForComparison as RecipientForComparison,
)
from app.application.use_cases.whatsapp.group_match_types import (
    SubmissionForComparison as SubmissionForComparison,
)
from app.application.use_cases.whatsapp.group_match_types import (
    SubmissionMatchRow as SubmissionMatchRow,
)
from app.application.use_cases.whatsapp.group_match_types import (
    SubmissionMatchSummary as SubmissionMatchSummary,
)
from app.application.use_cases.whatsapp.group_match_types import (
    _IdentityProfile as _IdentityProfile,
)
from app.application.use_cases.whatsapp.group_match_types import (
    _LogicalRecipient as _LogicalRecipient,
)
from app.application.use_cases.whatsapp.group_match_types import (
    _PairEvidence as _PairEvidence,
)
