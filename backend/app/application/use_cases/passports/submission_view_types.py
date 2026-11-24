"""Roster view types with explicit projection boundaries."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SubmissionViewEntry:
    submission: Any
    duplicate_cluster_id: str | None
    duplicate_cluster_size: int
    duplicate_cluster_member_ids: tuple[uuid.UUID, ...]
    verification_confidence: float | None


@dataclass(frozen=True)
class ExpiryAlert:
    submission_id: uuid.UUID
    client_name: str
    client_email: str | None
    passport_number: str | None
    date_of_expiry: str
    status: str


@dataclass(frozen=True)
class DuplicateClusterPage:
    cluster_id: str
    total_members: int
    matching_members: int
    visible_member_ids: tuple[uuid.UUID, ...]
    first_page: int
    last_page: int


@dataclass(frozen=True)
class SubmissionViewResult:
    items: tuple[SubmissionViewEntry, ...]
    ordered_submission_ids: tuple[uuid.UUID, ...]
    group_total: int
    total: int
    page: int
    page_size: int
    total_pages: int
    returned_count: int
    duplicate_clusters: tuple[DuplicateClusterPage, ...]
    cluster_boundaries_preserved: bool
    expiry_alerts: tuple[ExpiryAlert, ...]
    document_follow_up_count: int = 0


@dataclass(frozen=True)
class SubmissionViewIdentity:
    id: uuid.UUID
    extraction_revision: int
    updated_at: datetime


@dataclass(frozen=True)
class PreparedSubmissionView:
    """Reusable computed index; full document payloads are never retained here."""

    pages: tuple[tuple[SubmissionViewEntry, ...], ...]
    clusters: tuple[tuple[DuplicateClusterPage, ...], ...]
    ordered_submission_ids: tuple[uuid.UUID, ...]
    group_total: int
    total: int
    page_size: int
    cluster_boundaries_preserved: bool
    expiry_alerts: tuple[ExpiryAlert, ...]
    document_follow_up_count: int = 0

    def page(self, number: int) -> SubmissionViewResult:
        items = self.pages[number - 1] if 0 < number <= len(self.pages) else ()
        clusters = self.clusters[number - 1] if 0 < number <= len(self.clusters) else ()
        return SubmissionViewResult(
            items=items,
            ordered_submission_ids=self.ordered_submission_ids,
            group_total=self.group_total,
            total=self.total,
            page=number,
            page_size=self.page_size,
            total_pages=len(self.pages),
            returned_count=len(items),
            duplicate_clusters=clusters,
            cluster_boundaries_preserved=self.cluster_boundaries_preserved,
            expiry_alerts=self.expiry_alerts,
            document_follow_up_count=self.document_follow_up_count,
        )
