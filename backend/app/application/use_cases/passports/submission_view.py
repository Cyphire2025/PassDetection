"""Prepare the duplicate-aware roster through focused, reusable view owners."""

from __future__ import annotations

import calendar as calendar
import math as math
import re as re
import unicodedata as unicodedata
import uuid as uuid
from dataclasses import dataclass as dataclass
from datetime import UTC as UTC
from datetime import date as date
from datetime import datetime as datetime
from typing import Any as Any

from app.domain.value_objects.passport_fields import (
    canonical_country_identity as canonical_country_identity,
)

from .submission_view_clustering import (
    _build_blocks as _build_blocks,
)
from .submission_view_expiry import (
    _add_months as _add_months,
)
from .submission_view_expiry import (
    _expiry_alerts as _expiry_alerts,
)
from .submission_view_fields import (
    _cluster_id as _cluster_id,
)
from .submission_view_fields import (
    _display_name as _display_name,
)
from .submission_view_fields import (
    _field_value as _field_value,
)
from .submission_view_fields import (
    _normalized_identifier as _normalized_identifier,
)
from .submission_view_fields import (
    _normalized_tokens as _normalized_tokens,
)
from .submission_view_fields import (
    _passport_name as _passport_name,
)
from .submission_view_fields import (
    _place_of_issue_identity as _place_of_issue_identity,
)
from .submission_view_fields import (
    _verification_confidence as _verification_confidence,
)
from .submission_view_fields import (
    duplicate_identity_key as duplicate_identity_key,
)
from .submission_view_ordering import (
    _matches_normalized_search as _matches_normalized_search,
)
from .submission_view_ordering import (
    _matches_search as _matches_search,
)
from .submission_view_ordering import (
    _sort_blocks as _sort_blocks,
)
from .submission_view_ordering import (
    _sort_entries as _sort_entries,
)
from .submission_view_ordering import (
    _sort_value as _sort_value,
)
from .submission_view_ordering import (
    _status_matches as _status_matches,
)
from .submission_view_pagination import (
    _all_page_clusters as _all_page_clusters,
)
from .submission_view_pagination import (
    _paginate_blocks as _paginate_blocks,
)
from .submission_view_types import (
    DuplicateClusterPage as DuplicateClusterPage,
)
from .submission_view_types import (
    ExpiryAlert as ExpiryAlert,
)
from .submission_view_types import (
    PreparedSubmissionView as PreparedSubmissionView,
)
from .submission_view_types import (
    SubmissionViewEntry as SubmissionViewEntry,
)
from .submission_view_types import (
    SubmissionViewIdentity as SubmissionViewIdentity,
)
from .submission_view_types import (
    SubmissionViewResult as SubmissionViewResult,
)


def build_submission_view(
    submissions: list[Any],
    *,
    submission_filter: str,
    sort_by: str,
    sort_order: str,
    search: str | None,
    page: int,
    page_size: int,
    today: date | None = None,
    travel_date: date | None = None,
) -> SubmissionViewResult:
    return prepare_submission_view(
        submissions,
        submission_filter=submission_filter,
        sort_by=sort_by,
        sort_order=sort_order,
        search=search,
        page_size=page_size,
        today=today,
        travel_date=travel_date,
    ).page(page)


def prepare_submission_view(
    submissions: list[Any],
    *,
    submission_filter: str,
    sort_by: str,
    sort_order: str,
    search: str | None,
    page_size: int,
    today: date | None = None,
    travel_date: date | None = None,
) -> PreparedSubmissionView:
    """Apply full-group identity logic before filters and block pagination."""

    blocks = _build_blocks(submissions)
    normalized_search = (search or "").strip()
    if normalized_search:
        search_needle = _normalized_tokens(normalized_search)
        blocks = [
            block
            for block in blocks
            if any(_matches_normalized_search(entry, search_needle) for entry in block)
        ]

    if submission_filter == "duplicates":
        blocks = [block for block in blocks if block[0].duplicate_cluster_id is not None]
    elif submission_filter != "all":
        # Search may select a whole cluster, but status filters remain
        # truthful at member level while retaining full cluster metadata.
        blocks = [
            matching
            for block in blocks
            if (matching := [entry for entry in block if _status_matches(entry, submission_filter)])
        ]

    blocks = _sort_blocks(blocks, sort_by=sort_by, sort_order=sort_order)
    ordered_submission_ids = tuple(entry.submission.id for block in blocks for entry in block)
    total = sum(len(block) for block in blocks)
    pages = _paginate_blocks(blocks, page_size)
    return PreparedSubmissionView(
        pages=tuple(tuple(entries) for entries in pages),
        clusters=_all_page_clusters(pages),
        ordered_submission_ids=ordered_submission_ids,
        group_total=len(submissions),
        document_follow_up_count=sum(
            bool(getattr(row, "document_follow_up", False)) for row in submissions
        ),
        total=total,
        page_size=page_size,
        cluster_boundaries_preserved=all(len(block) <= page_size for block in blocks),
        expiry_alerts=_expiry_alerts(
            submissions,
            today=today or datetime.now(tz=UTC).date(),
            travel_date=travel_date,
        ),
    )
