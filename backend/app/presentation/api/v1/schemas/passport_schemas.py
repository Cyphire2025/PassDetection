"""Stable passport schema imports grouped by their API responsibility."""

import uuid as uuid
from datetime import date as date
from datetime import datetime as datetime
from typing import Literal as Literal

from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import EmailStr as EmailStr
from pydantic import Field as Field
from pydantic import field_validator as field_validator
from pydantic import model_validator as model_validator

from app.domain.value_objects.phone_number import normalize_phone_number as normalize_phone_number
from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE as DEFAULT_TRIP_TIMEZONE

from .passport_bulk_schemas import (
    BulkDeletePassportSubmissionsRequest as BulkDeletePassportSubmissionsRequest,
)
from .passport_bulk_schemas import (
    BulkDeletePassportSubmissionsResponse as BulkDeletePassportSubmissionsResponse,
)
from .passport_bulk_schemas import (
    BulkDocumentFollowUpRequest as BulkDocumentFollowUpRequest,
)
from .passport_bulk_schemas import (
    BulkDocumentFollowUpResponse as BulkDocumentFollowUpResponse,
)
from .passport_bulk_schemas import (
    BulkStaffApprovePassportSelection as BulkStaffApprovePassportSelection,
)
from .passport_bulk_schemas import (
    BulkStaffApprovePassportSubmissionsRequest as BulkStaffApprovePassportSubmissionsRequest,
)
from .passport_bulk_schemas import (
    BulkStaffApprovePassportSubmissionsResponse as BulkStaffApprovePassportSubmissionsResponse,
)
from .passport_bulk_schemas import (
    BulkStaffApproveSkippedSubmission as BulkStaffApproveSkippedSubmission,
)
from .passport_bulk_schemas import (
    ExportSelectedGroupsRequest as ExportSelectedGroupsRequest,
)
from .passport_bulk_schemas import (
    ExportSelectedPassportImagesRequest as ExportSelectedPassportImagesRequest,
)
from .passport_bulk_schemas import (
    ExportSelectedPassportsRequest as ExportSelectedPassportsRequest,
)
from .passport_collection_schemas import (
    ClientCustomAnswerRequest as ClientCustomAnswerRequest,
)
from .passport_collection_schemas import (
    ClientCustomDetailAnswerRequest as ClientCustomDetailAnswerRequest,
)
from .passport_collection_schemas import (
    ClientSubmitPassportRequest as ClientSubmitPassportRequest,
)
from .passport_collection_schemas import (
    ConfirmPassportSubmissionRequest as ConfirmPassportSubmissionRequest,
)
from .passport_collection_schemas import (
    ReconcilePassportUploadRequest as ReconcilePassportUploadRequest,
)
from .passport_collection_schemas import (
    ReconcilePassportUploadResponse as ReconcilePassportUploadResponse,
)
from .passport_collection_schemas import (
    StaffApprovePassportRequest as StaffApprovePassportRequest,
)
from .passport_document_schemas import (
    ImportPassportGroupResponse as ImportPassportGroupResponse,
)
from .passport_document_schemas import (
    PassengerQrStatusResponse as PassengerQrStatusResponse,
)
from .passport_document_schemas import (
    PassportDocumentImportItem as PassportDocumentImportItem,
)
from .passport_document_schemas import (
    PassportDocumentImportPreviewResponse as PassportDocumentImportPreviewResponse,
)
from .passport_document_schemas import (
    PassportDocumentImportSaveResponse as PassportDocumentImportSaveResponse,
)
from .passport_document_schemas import (
    PassportExtractionConflictResponse as PassportExtractionConflictResponse,
)
from .passport_editing_schemas import (
    PassportImageCropCoordinates as PassportImageCropCoordinates,
)
from .passport_editing_schemas import (
    PassportImageCropResetRequest as PassportImageCropResetRequest,
)
from .passport_editing_schemas import (
    PassportImageCropResponse as PassportImageCropResponse,
)
from .passport_editing_schemas import (
    PassportImageCropUpdateRequest as PassportImageCropUpdateRequest,
)
from .passport_editing_schemas import (
    PassportImageTypeValue as PassportImageTypeValue,
)
from .passport_editing_schemas import (
    PassportVisaAiImageJobResponse as PassportVisaAiImageJobResponse,
)
from .passport_editing_schemas import (
    PassportVisaAiImageListResponse as PassportVisaAiImageListResponse,
)
from .passport_editing_schemas import (
    PassportVisaAiImageResponse as PassportVisaAiImageResponse,
)
from .passport_editing_schemas import (
    PassportVisaAiImageUseRequest as PassportVisaAiImageUseRequest,
)
from .passport_editing_schemas import (
    PassportVisaAiPreviewRequest as PassportVisaAiPreviewRequest,
)
from .passport_export_schemas import (
    PassportExportFieldOptionResponse as PassportExportFieldOptionResponse,
)
from .passport_export_schemas import (
    PassportExportFieldOptionsResponse as PassportExportFieldOptionsResponse,
)
from .passport_export_schemas import (
    PassportExportGroupingOptionResponse as PassportExportGroupingOptionResponse,
)
from .passport_export_schemas import (
    PassportExportHistoryCompletionResponse as PassportExportHistoryCompletionResponse,
)
from .passport_export_schemas import (
    PassportExportHistoryDetailResponse as PassportExportHistoryDetailResponse,
)
from .passport_export_schemas import (
    PassportExportHistoryItemResponse as PassportExportHistoryItemResponse,
)
from .passport_export_schemas import (
    PassportExportHistoryListResponse as PassportExportHistoryListResponse,
)
from .passport_export_schemas import (
    PassportExportHistorySubmissionResponse as PassportExportHistorySubmissionResponse,
)
from .passport_export_schemas import (
    PassportSelectedGroupsExportFieldOptionsResponse as PassportSelectedGroupsExportFieldOptionsResponse,
)
from .passport_summary_schemas import (
    PassportGroupSummaryResponse as PassportGroupSummaryResponse,
)
from .passport_verification_schemas import (
    PassportVerificationFieldName as PassportVerificationFieldName,
)
from .passport_verification_schemas import (
    PostSubmissionFieldOutcomeResponse as PostSubmissionFieldOutcomeResponse,
)
from .passport_verification_schemas import (
    PostSubmissionVerificationResponse as PostSubmissionVerificationResponse,
)
from .passport_view_schemas import (
    PassportDuplicateClusterPageResponse as PassportDuplicateClusterPageResponse,
)
from .passport_view_schemas import (
    PassportExpiryAlertResponse as PassportExpiryAlertResponse,
)
from .passport_view_schemas import (
    PassportSubmissionResponse as PassportSubmissionResponse,
)
from .passport_view_schemas import (
    PassportSubmissionSelectionSnapshotResponse as PassportSubmissionSelectionSnapshotResponse,
)
from .passport_view_schemas import (
    PassportSubmissionsViewResponse as PassportSubmissionsViewResponse,
)
from .passport_view_schemas import (
    PassportSubmissionViewItemResponse as PassportSubmissionViewItemResponse,
)
