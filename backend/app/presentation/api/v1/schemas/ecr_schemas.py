"""Public ECR batch contracts; storage locators never leave the backend."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateEcrBatch(BaseModel):
    title: str = Field(default="ECR check", min_length=1, max_length=160)
    expected_count: int = Field(ge=1, le=1000)


class EcrItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    original_filename: str
    status: Literal["queued", "processing", "completed", "failed"]
    result: Literal["ECR", "NA", "NEEDS_REVIEW"] | None
    reason: str | None


class EcrBatchSummary(BaseModel):
    batch_id: uuid.UUID
    title: str
    status: str
    total_count: int
    expected_count: int
    processed_count: int
    ecr_count: int
    na_count: int
    review_count: int
    failed_count: int
    created_at: datetime


class EcrBatchResponse(EcrBatchSummary):
    items: list[EcrItemResponse]
