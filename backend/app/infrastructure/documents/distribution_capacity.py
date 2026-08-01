"""Resource bounds for document-to-passenger assignment expansion."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Final

MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_BATCH: Final[int] = 3_000
MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE: Final[int] = 3_000


class DocumentDistributionCapacityError(ValueError):
    """Raised before persistence when a distribution row budget would be exceeded."""

    def __init__(
        self,
        *,
        limit: int = MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_BATCH,
        scope: str = "batch",
    ) -> None:
        self.limit = limit
        self.scope = scope
        if scope == "group_document_type":
            message = (
                f"This group already has the maximum {limit:,} document assignments "
                "for this document type. Remove obsolete documents before uploading more."
            )
        elif scope == "batch":
            message = (
                f"This upload would create more than {limit:,} document assignments "
                "in one batch. Upload fewer combined PDFs at a time."
            )
        else:
            raise ValueError("Unsupported distribution capacity scope")
        super().__init__(message)


def enforce_distribution_assignment_capacity(
    *,
    existing_rows: int,
    match_groups: Iterable[Collection[object]],
    limit: int = MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_BATCH,
) -> int:
    """Return the projected row count or fail before storage and database writes."""

    if existing_rows < 0:
        raise ValueError("The existing assignment count cannot be negative")
    if limit < 1:
        raise ValueError("The assignment capacity must be positive")

    projected_rows = existing_rows
    for matches in match_groups:
        projected_rows += len(matches)
        if projected_rows > limit:
            raise DocumentDistributionCapacityError(limit=limit)
    return projected_rows


def enforce_distribution_scope_capacity(
    *,
    existing_rows: int,
    incoming_rows: int,
    limit: int = MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE,
) -> int:
    """Return the bounded scope total or reject before relational persistence."""

    if existing_rows < 0 or incoming_rows < 0:
        raise ValueError("Distribution assignment counts cannot be negative")
    if limit < 1:
        raise ValueError("The assignment capacity must be positive")
    projected_rows = existing_rows + incoming_rows
    if projected_rows > limit:
        raise DocumentDistributionCapacityError(
            limit=limit,
            scope="group_document_type",
        )
    return projected_rows
