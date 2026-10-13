"""Combine ordinary submissions from the exact visible company group population.

Two database queries, O(page_size) application memory. Without name search, six
disjoint status branches each retain at most K=page_size+1 IDs before a <=6K
merge. Existing agency/status/created indexes permit newest-first scans; sparse
company membership or equal timestamps can still require additional DB work.
Name search retains the existing trigram prefilter. No capacity claim is made.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from app.application.companies.access import (
    COMPANY_ADMIN_ROLES,
    require_company,
    visible_company_groups,
)
from app.application.mcp.read_cursor import MCPReadCursor
from app.core.config.settings import Settings, get_settings
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, User
from app.domain.exceptions.exceptions import ValidationError
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.search_expressions import (
    passport_search_fields,
    substring_predicate,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.companies import _private_response
from app.presentation.api.v1.schemas.company_submission_schemas import (
    CompanySubmissionPage,
    CompanySubmissionResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter(dependencies=[Depends(_private_response)])


def _recent_submission_ids(
    groups: Subquery, conditions: list[ColumnElement[bool]], limit: int,
) -> Subquery:
    """Each disjoint branch needs only its top K to contain the global top K.

    Keep visibility inside each branch before LIMIT. Correlated membership lets
    the agency/status/created index drive ordered scans instead of sorting every
    group's rows. Ties retain the same UUID ordering as the signed cursor.
    """
    submission = PassportSubmissionModel
    visible = select(groups.c.id).where(groups.c.id == submission.group_id).correlate(submission).exists()
    eligible = select(submission.id, submission.created_at).where(*conditions, visible)
    branches = [select(eligible.where(submission.status == status)
        .order_by(submission.created_at.desc(), submission.id.desc()).limit(limit).subquery())
        for status in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES]
    candidates = union_all(*branches).subquery()
    return select(candidates).order_by(candidates.c.created_at.desc(), candidates.c.id.desc()).limit(limit).subquery()


@router.get("/{company_id}/submissions", response_model=CompanySubmissionPage)
async def company_submissions(
    company_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    search: str = Query(default="", max_length=120), cursor: str | None = Query(default=None, max_length=2048),
    page_size: int = Query(default=25, ge=1, le=100),
    user: User = Depends(require_role(COMPANY_ADMIN_ROLES)), session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> CompanySubmissionPage:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    normalized = " ".join(search.split()).lower()
    if normalized and len(normalized) < 3:
        raise ValidationError("Enter at least 3 characters to search names.", field="search")
    codec = MCPReadCursor(settings.app_secret_key, "company-submissions-v1")
    try:
        state = codec.read(cursor, {"actor": user.id, "agency": company.agency_id,
                                    "company": company.id, "search": normalized})
    except ValueError as exc:
        raise ValidationError(str(exc), field="cursor") from exc
    groups = visible_company_groups(user, company.agency_id, company.id).with_only_columns(
        ClientGroupModel.id, ClientGroupModel.name, ClientGroupModel.travel_date,
    ).subquery()
    submission = PassportSubmissionModel
    conditions: list[ColumnElement[bool]] = [
        submission.agency_id == company.agency_id,
        submission.created_at <= datetime.fromisoformat(state["cutoff"]),
    ]
    if after := codec.after(state):
        conditions.append(or_(submission.created_at < after[0], and_(
            submission.created_at == after[0], submission.id < after[1],
        )))
    fields = (
        submission.id, submission.group_id, groups.c.name.label("group_name"), groups.c.travel_date,
        submission.client_name.label("display_name"), submission.status, submission.created_at,
    )
    if normalized:
        # Exact name predicates remain mandatory: a phone/passport match in the
        # existing combined trigram expression never makes a record visible.
        names = (submission.client_name, *(column[name].as_string()
                 for name in ("surname", "given_names")
                 for column in (submission.extracted_fields, submission.confirmed_fields)))
        query = select(*fields).join(groups, groups.c.id == submission.group_id).where(
            *conditions, submission.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
            substring_predicate(normalized, fields=names, indexed_fields=passport_search_fields()),
        )
    else:
        recent = _recent_submission_ids(groups, conditions, page_size + 1)
        query = select(*fields).select_from(recent).join(submission, submission.id == recent.c.id).join(
            groups, groups.c.id == submission.group_id,
        )
    rows = list((await session.execute(query.order_by(submission.created_at.desc(), submission.id.desc())
                                      .limit(page_size + 1))).mappings())
    has_more, rows = len(rows) > page_size, rows[:page_size]
    return CompanySubmissionPage(
        items=[CompanySubmissionResponse.model_validate(dict(row)) for row in rows],
        next_cursor=codec.next(state, dict(rows[-1])) if has_more else None, has_more=has_more,
    )
