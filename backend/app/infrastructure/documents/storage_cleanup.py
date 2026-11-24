"""Stable encrypted storage-cleanup API and compatibility exports."""

import base64 as base64
import hashlib as hashlib
import json as json
import re as re
import uuid as uuid
from collections.abc import Callable as Callable
from collections.abc import Mapping as Mapping
from collections.abc import Sequence as Sequence
from dataclasses import dataclass as dataclass
from datetime import UTC as UTC
from datetime import datetime as datetime
from datetime import timedelta as timedelta

from cryptography.fernet import Fernet as Fernet
from cryptography.fernet import InvalidToken as InvalidToken
from sqlalchemy import and_ as and_
from sqlalchemy import or_ as or_
from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker as async_sessionmaker

from app.core.config.settings import get_settings as get_settings
from app.core.logging.logger import get_logger as get_logger
from app.infrastructure.database.models import AuditLogModel as AuditLogModel
from app.infrastructure.database.models import StorageCleanupJobModel as StorageCleanupJobModel
from app.infrastructure.database.session import AsyncSessionFactory as AsyncSessionFactory
from app.infrastructure.observability.metrics import metrics as metrics
from app.infrastructure.storage.minio_repository import (
    MinioStorageRepository as MinioStorageRepository,
)

from .storage_cleanup_cipher import StorageCleanupCipher as StorageCleanupCipher
from .storage_cleanup_cipher import _secret_value as _secret_value
from .storage_cleanup_cipher import _storage_cleanup_fernet as _storage_cleanup_fernet
from .storage_cleanup_execution import (
    _execute_storage_cleanup_claim as _execute_storage_cleanup_claim,
)
from .storage_cleanup_execution import logger as logger
from .storage_cleanup_execution import (
    process_due_storage_cleanup_jobs as process_due_storage_cleanup_jobs,
)
from .storage_cleanup_execution import process_storage_cleanup_job as process_storage_cleanup_job
from .storage_cleanup_leases import _claim_storage_cleanup_job as _claim_storage_cleanup_job
from .storage_cleanup_leases import _complete_storage_cleanup_job as _complete_storage_cleanup_job
from .storage_cleanup_leases import _defer_storage_cleanup_job as _defer_storage_cleanup_job
from .storage_cleanup_policy import _CANONICAL_PASSPORT_OBJECT_KEY as _CANONICAL_PASSPORT_OBJECT_KEY
from .storage_cleanup_policy import _UUID_PATH_SEGMENT as _UUID_PATH_SEGMENT
from .storage_cleanup_policy import MAX_STORAGE_CLEANUP_ATTEMPTS as MAX_STORAGE_CLEANUP_ATTEMPTS
from .storage_cleanup_policy import MAX_STORAGE_CLEANUP_KEY_LENGTH as MAX_STORAGE_CLEANUP_KEY_LENGTH
from .storage_cleanup_policy import MAX_STORAGE_CLEANUP_KEYS as MAX_STORAGE_CLEANUP_KEYS
from .storage_cleanup_policy import STORAGE_CLEANUP_KEY_VERSION as STORAGE_CLEANUP_KEY_VERSION
from .storage_cleanup_policy import STORAGE_CLEANUP_LEASE_SECONDS as STORAGE_CLEANUP_LEASE_SECONDS
from .storage_cleanup_policy import STORAGE_CLEANUP_SOURCES as STORAGE_CLEANUP_SOURCES
from .storage_cleanup_policy import _storage_key_matches_source as _storage_key_matches_source
from .storage_cleanup_policy import _validated_storage_keys as _validated_storage_keys
from .storage_cleanup_staging import (
    _stage_validated_storage_cleanup_job as _stage_validated_storage_cleanup_job,
)
from .storage_cleanup_staging import persist_storage_cleanup_job as persist_storage_cleanup_job
from .storage_cleanup_staging import stage_storage_cleanup_job as stage_storage_cleanup_job
from .storage_cleanup_staging import stage_storage_cleanup_jobs as stage_storage_cleanup_jobs
from .storage_cleanup_types import StorageCleanupClaim as StorageCleanupClaim
from .storage_cleanup_types import StorageCleanupIncompleteError as StorageCleanupIncompleteError
from .storage_cleanup_types import StorageCleanupPayloadError as StorageCleanupPayloadError
from .storage_cleanup_types import StorageCleanupResult as StorageCleanupResult
