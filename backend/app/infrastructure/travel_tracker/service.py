"""Stable tracker service API coordinating current actor and focused domain owners."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.application.dtos.travel_tracker import (
    TrackerCounts,
    TrackerGroup,
    TrackerGroupList,
    TrackerImportPreview,
    TrackerMarkRequest,
    TrackerMarkResponse,
    TrackerPassenger,
    TrackerStatus,
    TrackerTrack,
    TrackerWorkspace,
)
from app.domain.entities.entities import User
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.travel_tracker_model import TravelTrackerModel
from app.infrastructure.travel_tracker import changes, files, projections, queries, reads
from app.infrastructure.travel_tracker.actor import lock_tracker_actor
from app.infrastructure.travel_tracker.queries import TRACKER_ROLES as TRACKER_ROLES


class TravelTrackerService:
    def __init__(
        self,
        session: AsyncSession,
        user: User,
        *,
        allowed_group_ids: Sequence[uuid.UUID] | None = None,
        actor_already_fenced: bool = False,
    ) -> None:
        self.session, self.user = (session, user)
        self.allowed_group_ids = tuple(allowed_group_ids) if allowed_group_ids is not None else None
        # MCP already holds an owner SHARE fence; an UPDATE upgrade can
        # deadlock concurrent calls from the same owner.
        self.actor_already_fenced = actor_already_fenced

    def _require_role(self) -> None:
        return queries.require_role(self.user)

    def _group_query(self) -> Select[tuple[ClientGroupModel]]:
        return queries.group_query(self.user, self.allowed_group_ids)

    async def _group(self, group_id: uuid.UUID, *, lock: bool = False) -> ClientGroupModel:
        return await queries.load_group(
            self.session, self.user, self.allowed_group_ids, group_id, lock=lock
        )

    @staticmethod
    def _join() -> ColumnElement[bool]:
        return queries.tracker_join()

    def _roster(
        self, group: ClientGroupModel
    ) -> Select[tuple[PassportSubmissionModel, TravelTrackerModel]]:
        return queries.roster(group)

    @staticmethod
    def _validate_filters(track: str, status: str, search: str | None) -> None:
        return queries.validate_filters(track, status, search)

    @staticmethod
    def _page(page: int, page_size: int, maximum: int = 200) -> None:
        return queries.validate_page(page, page_size, maximum)

    @staticmethod
    def _field_expression(key: str) -> ColumnElement[str]:
        return queries.field_expression(key)

    def _filter(
        self,
        statement: Select[tuple[PassportSubmissionModel, TravelTrackerModel]],
        *,
        track: TrackerTrack,
        status: TrackerStatus,
        search: str | None,
    ) -> Select[tuple[PassportSubmissionModel, TravelTrackerModel]]:
        return queries.filter_roster(statement, track=track, status=status, search=search)

    async def _summary(self, groups: list[ClientGroupModel]) -> dict[uuid.UUID, TrackerGroup]:
        return await queries.group_summary(self.session, groups)

    @staticmethod
    def _counts(summary: TrackerGroup, track: TrackerTrack) -> TrackerCounts:
        return projections.counts(summary, track)

    async def list_groups(
        self, *, search: str | None = None, page: int = 1, page_size: int = 24
    ) -> TrackerGroupList:
        return await reads.list_groups(
            self.session,
            self.user,
            self.allowed_group_ids,
            search=search,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    def _passenger(
        passenger: PassportSubmissionModel, tracker: TravelTrackerModel | None
    ) -> TrackerPassenger:
        return projections.project_passenger(passenger, tracker)

    async def workspace(
        self,
        group_id: uuid.UUID,
        *,
        track: TrackerTrack = "visa",
        status: TrackerStatus = "all",
        search: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> TrackerWorkspace:
        return await reads.workspace(
            self.session,
            self.user,
            self.allowed_group_ids,
            group_id,
            track=track,
            status=status,
            search=search,
            page=page,
            page_size=page_size,
        )

    async def mark(
        self, group_id: uuid.UUID, body: TrackerMarkRequest, *, commit: bool = True
    ) -> TrackerMarkResponse:
        self._require_role()
        if not self.actor_already_fenced:
            self.user = await lock_tracker_actor(self.session, self.user)
        self._require_role()
        return await changes.mark_authorized(
            self.session, self.user, self.allowed_group_ids, group_id, body, commit=commit
        )

    async def export(
        self,
        group_id: uuid.UUID,
        *,
        track: TrackerTrack = "visa",
        status: TrackerStatus = "all",
        search: str | None = None,
    ) -> tuple[bytes, str]:
        return await files.export(
            self.session,
            self.user,
            self.allowed_group_ids,
            group_id,
            track=track,
            status=status,
            search=search,
        )

    async def preview(
        self,
        group_id: uuid.UUID,
        *,
        content: bytes,
        filename: str,
        track: TrackerTrack = "visa",
        marked: bool = True,
    ) -> TrackerImportPreview:
        return await files.preview(
            self.session,
            self.user,
            self.allowed_group_ids,
            group_id,
            content=content,
            filename=filename,
            track=track,
            marked=marked,
        )
