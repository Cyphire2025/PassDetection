"""Revalidate current tenant/group visibility before exposing AI-linked records."""

from __future__ import annotations

import uuid
from typing import Literal, TypeAlias, cast

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.email_models import EmailMessageModel
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.presentation.api.v1.routes.email_ai_inbox_responses import _result_group_id
from app.presentation.api.v1.schemas.email_ai_schemas import EmailCandidateLinkResponse

CandidateEntityType = Literal["group", "passenger"]


ResolvedCandidateLink: TypeAlias = tuple[
    CandidateEntityType,
    uuid.UUID,
    float,
    str,
]


async def _load_visible_linked_groups(
    session: AsyncSession,
    *,
    analyses_and_messages: list[tuple[EmailAiAnalysisModel, EmailMessageModel]],
    current_user: User,
) -> dict[uuid.UUID, ClientGroupModel]:
    candidates: dict[
        uuid.UUID,
        tuple[uuid.UUID | None, uuid.UUID | None, uuid.UUID],
    ] = {}
    pair_predicates: list[ColumnElement[bool]] = []
    for analysis, message in analyses_and_messages:
        ai_group_id = _result_group_id(analysis)
        message_group_id = message.group_id
        primary_id = ai_group_id or message_group_id
        fallback_id = message_group_id if ai_group_id is not None else None
        candidates[analysis.id] = (
            primary_id,
            fallback_id,
            analysis.agency_id,
        )
        for group_id in (ai_group_id, message_group_id):
            if group_id is None:
                continue
            pair_predicates.append(
                and_(
                    ClientGroupModel.id == group_id,
                    ClientGroupModel.agency_id == analysis.agency_id,
                )
            )
    if not pair_predicates:
        return {}

    statement = select(ClientGroupModel).where(or_(*pair_predicates))
    result = await session.execute(
        AuthorizationPolicy.apply_group_visibility_scope(
            statement,
            current_user,
        )
    )
    visible_by_pair = {(group.agency_id, group.id): group for group in result.scalars().all()}
    visible_by_analysis: dict[uuid.UUID, ClientGroupModel] = {}
    for analysis_id, (primary_id, fallback_id, agency_id) in candidates.items():
        group = visible_by_pair.get((agency_id, primary_id)) if primary_id is not None else None
        if group is None and fallback_id is not None:
            group = visible_by_pair.get((agency_id, fallback_id))
        if group is not None:
            visible_by_analysis[analysis_id] = group
    return visible_by_analysis


async def _load_visible_linked_passengers(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    current_user: User,
) -> list[tuple[uuid.UUID, str]]:
    result_json = analysis.result_json or {}
    raw_ids = result_json.get("linked_passenger_ids", [])
    if not isinstance(raw_ids, list):
        return []
    linked_ids: list[uuid.UUID] = []
    for value in raw_ids[:100]:
        try:
            linked_ids.append(uuid.UUID(str(value)))
        except (TypeError, ValueError):
            continue
    if not linked_ids:
        return []
    statement = select(
        PassportSubmissionModel.id,
        PassportSubmissionModel.client_name,
    ).where(
        PassportSubmissionModel.id.in_(linked_ids),
        PassportSubmissionModel.agency_id == analysis.agency_id,
    )
    visible_result = await session.execute(
        AuthorizationPolicy.apply_passport_visibility_scope(
            statement,
            current_user,
        )
    )
    visible = {row.id: row.client_name for row in visible_result.all()}
    return [
        (passenger_id, visible[passenger_id])
        for passenger_id in linked_ids
        if passenger_id in visible
    ]


async def _load_visible_candidate_links(
    session: AsyncSession,
    *,
    analysis: EmailAiAnalysisModel,
    current_user: User,
    canonical_passenger_ids: set[uuid.UUID],
) -> list[EmailCandidateLinkResponse]:
    """Resolve provider aliases back to currently visible, live records only."""

    result_json = analysis.result_json or {}
    raw_links = result_json.get("candidate_links")
    manifest_aliases = (analysis.context_manifest or {}).get("aliases")
    if not isinstance(raw_links, list) or not isinstance(manifest_aliases, dict):
        return []

    aliases = cast(dict[object, object], manifest_aliases)
    resolved: list[ResolvedCandidateLink] = []
    seen: set[tuple[CandidateEntityType, uuid.UUID]] = set()
    for raw_link in raw_links[:24]:
        candidate = _parse_candidate_link(raw_link, aliases)
        if candidate is None:
            continue
        entity_type, entity_id, confidence, rationale = candidate
        key = (entity_type, entity_id)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(candidate)
    if not resolved:
        return []

    group_ids = [entity_id for entity_type, entity_id, _, _ in resolved if entity_type == "group"]
    passenger_ids = [
        entity_id for entity_type, entity_id, _, _ in resolved if entity_type == "passenger"
    ]
    visible_names: dict[tuple[CandidateEntityType, uuid.UUID], str] = {}
    if group_ids:
        group_statement = select(
            ClientGroupModel.id,
            ClientGroupModel.name,
        ).where(
            ClientGroupModel.id.in_(group_ids),
            ClientGroupModel.agency_id == analysis.agency_id,
            ClientGroupModel.status.notin_({"archived", "deleted"}),
        )
        group_result = await session.execute(
            AuthorizationPolicy.apply_group_visibility_scope(
                group_statement,
                current_user,
            )
        )
        visible_names.update(
            {
                ("group", row.id): row.name
                for row in group_result.all()
                if isinstance(row.name, str) and row.name.strip()
            }
        )
    if passenger_ids:
        passenger_statement = select(
            PassportSubmissionModel.id,
            PassportSubmissionModel.client_name,
        ).where(
            PassportSubmissionModel.id.in_(passenger_ids),
            PassportSubmissionModel.agency_id == analysis.agency_id,
            PassportSubmissionModel.status != "failed",
        )
        passenger_result = await session.execute(
            AuthorizationPolicy.apply_passport_visibility_scope(
                passenger_statement,
                current_user,
            )
        )
        visible_names.update(
            {
                ("passenger", row.id): row.client_name
                for row in passenger_result.all()
                if isinstance(row.client_name, str) and row.client_name.strip()
            }
        )

    canonical_group_id = _result_group_id(analysis)
    return [
        EmailCandidateLinkResponse(
            entity_type=entity_type,
            entity_id=entity_id,
            name=visible_names[(entity_type, entity_id)],
            confidence=confidence,
            rationale=rationale,
            canonical=(
                entity_id == canonical_group_id
                if entity_type == "group"
                else entity_id in canonical_passenger_ids
            ),
        )
        for entity_type, entity_id, confidence, rationale in resolved
        if (entity_type, entity_id) in visible_names
    ]


def _parse_candidate_link(
    raw_link: object,
    aliases: dict[object, object],
) -> ResolvedCandidateLink | None:
    """Validate one provider candidate before any tenant-scoped lookup."""

    if not isinstance(raw_link, dict):
        return None
    candidate = cast(dict[object, object], raw_link)
    alias = candidate.get("alias")
    confidence = candidate.get("confidence")
    rationale = candidate.get("rationale")
    alias_record = aliases.get(alias) if isinstance(alias, str) else None
    if not isinstance(alias_record, dict):
        return None
    alias_values = cast(dict[object, object], alias_record)
    entity_type_value = alias_values.get("entity_type")
    if (
        entity_type_value not in {"group", "passenger"}
        or not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= float(confidence) <= 1
        or not isinstance(rationale, str)
    ):
        return None
    try:
        entity_id = uuid.UUID(str(alias_values.get("entity_id")))
    except (TypeError, ValueError):
        return None
    entity_type: CandidateEntityType = "group" if entity_type_value == "group" else "passenger"
    return entity_type, entity_id, float(confidence), rationale.strip()[:320]
