"""Authorized tracker queries and atomic, attributed readiness changes."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import and_, case, func, or_, select
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
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import ImageValidationError
from app.domain.exceptions.travel_tracker import TravelTrackerError
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.travel_tracker_model import TravelTrackerModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read
from app.infrastructure.security.upload_validator import malware_scanner_from_settings
from app.infrastructure.travel_tracker.actor import lock_tracker_actor
from app.infrastructure.travel_tracker.spreadsheets import (
    MAX_EXPORT_ROWS,
    MAX_UPLOAD_BYTES,
    TrackerSpreadsheetError,
    build_export,
    field_values,
    full_name,
    match_rows,
    read_rows,
    text_value,
)
from app.infrastructure.travel_tracker.threading import run_tracker_work

TRACKER_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
}


class TravelTrackerService:
    def __init__(
        self,
        session: AsyncSession,
        user: User,
        *,
        allowed_group_ids: Sequence[uuid.UUID] | None = None,
        actor_already_fenced: bool = False,
    ) -> None:
        self.session, self.user = session, user
        self.allowed_group_ids = tuple(allowed_group_ids) if allowed_group_ids is not None else None
        # MCP authentication holds an owner row SHARE fence. Upgrading that
        # fence to UPDATE can deadlock simultaneous calls from the same owner.
        self.actor_already_fenced = actor_already_fenced

    def _require_role(self) -> None:
        if self.user.role not in TRACKER_ROLES:
            raise TravelTrackerError(status_code=403, detail="Insufficient permissions")

    def _group_query(self) -> Select[tuple[ClientGroupModel]]:
        self._require_role()
        statement = AuthorizationPolicy.apply_group_visibility_scope(
            select(ClientGroupModel).where(
                ClientGroupModel.deleted_at.is_(None),
                ClientGroupModel.status.in_(["active", "closed"]),
            ),
            self.user,
        )
        if self.allowed_group_ids is not None:
            statement = statement.where(ClientGroupModel.id.in_(self.allowed_group_ids))
        return cast(Select[tuple[ClientGroupModel]], statement)

    async def _group(self, group_id: uuid.UUID, *, lock: bool = False) -> ClientGroupModel:
        statement = self._group_query().where(ClientGroupModel.id == group_id)
        if lock:
            statement = statement.with_for_update(of=ClientGroupModel).execution_options(
                populate_existing=True
            )
        group = (await self.session.execute(statement)).scalar_one_or_none()
        if group is None:
            raise TravelTrackerError(status_code=404, detail="Client group was not found")
        return group

    @staticmethod
    def _join() -> ColumnElement[bool]:
        return and_(
            TravelTrackerModel.passenger_id == PassportSubmissionModel.id,
            TravelTrackerModel.group_id == PassportSubmissionModel.group_id,
            TravelTrackerModel.agency_id == PassportSubmissionModel.agency_id,
        )

    def _roster(
        self, group: ClientGroupModel
    ) -> Select[tuple[PassportSubmissionModel, TravelTrackerModel]]:
        # Every current imported/collected member appears, including extraction
        # and review states; explicit roster removals retain their normal scope.
        return (
            select(PassportSubmissionModel, TravelTrackerModel)
            .outerjoin(TravelTrackerModel, self._join())
            .where(
                PassportSubmissionModel.group_id == group.id,
                PassportSubmissionModel.agency_id == group.agency_id,
                operational_roster_member(),
            )
        )

    @staticmethod
    def _validate_filters(track: str, status: str, search: str | None) -> None:
        if track not in {"visa", "flight"} or status not in {"all", "marked", "pending"}:
            raise TravelTrackerError(status_code=422, detail="Invalid tracker filter")
        if search is not None and len(search) > 160:
            raise TravelTrackerError(
                status_code=422, detail="Search can contain at most 160 characters"
            )

    @staticmethod
    def _page(page: int, page_size: int, maximum: int = 200) -> None:
        if page < 1 or page > 100000 or page_size < 1 or page_size > maximum:
            raise TravelTrackerError(status_code=422, detail="Invalid pagination")

    @staticmethod
    def _field_expression(key: str) -> ColumnElement[str]:
        return func.coalesce(
            PassportSubmissionModel.confirmed_fields[key].as_string(),
            PassportSubmissionModel.extracted_fields[key].as_string(),
            "",
        )

    def _filter(
        self,
        statement: Select[tuple[PassportSubmissionModel, TravelTrackerModel]],
        *,
        track: TrackerTrack,
        status: TrackerStatus,
        search: str | None,
    ) -> Select[tuple[PassportSubmissionModel, TravelTrackerModel]]:
        self._validate_filters(track, status, search)
        flag = (
            TravelTrackerModel.visa_applied if track == "visa" else TravelTrackerModel.flight_booked
        )
        if status != "all":
            statement = statement.where(func.coalesce(flag, False).is_(status == "marked"))
        normalized = " ".join((search or "").split())
        if normalized:
            expression = func.trim(
                self._field_expression("given_names") + " " + self._field_expression("surname")
            )
            statement = statement.where(
                or_(
                    PassportSubmissionModel.client_name.icontains(normalized, autoescape=True),
                    PassportSubmissionModel.client_email.icontains(normalized, autoescape=True),
                    PassportSubmissionModel.client_phone.icontains(normalized, autoescape=True),
                    self._field_expression("passport_number").icontains(
                        normalized, autoescape=True
                    ),
                    expression.icontains(normalized, autoescape=True),
                )
            )
        return statement

    async def _summary(self, groups: list[ClientGroupModel]) -> dict[uuid.UUID, TrackerGroup]:
        counts = {}
        if groups:
            statement = (
                select(
                    PassportSubmissionModel.group_id,
                    func.count(PassportSubmissionModel.id),
                    func.sum(case((TravelTrackerModel.visa_applied.is_(True), 1), else_=0)),
                    func.sum(case((TravelTrackerModel.flight_booked.is_(True), 1), else_=0)),
                )
                .outerjoin(TravelTrackerModel, self._join())
                .where(
                    PassportSubmissionModel.group_id.in_([group.id for group in groups]),
                    operational_roster_member(),
                )
                .group_by(PassportSubmissionModel.group_id)
            )
            counts = {
                group_id: (int(total), int(visa or 0), int(flight or 0))
                for group_id, total, visa, flight in (await self.session.execute(statement)).all()
            }
        output = {}
        for group in groups:
            total, visa, flight = counts.get(group.id, (0, 0, 0))
            output[group.id] = TrackerGroup(
                id=group.id,
                name=group.name,
                destination=group.destination,
                travel_date=group.travel_date,
                return_date=group.return_date,
                status=group.status,
                total=total,
                visa_marked=visa,
                flight_marked=flight,
            )
        return output

    @staticmethod
    def _counts(summary: TrackerGroup, track: TrackerTrack) -> TrackerCounts:
        marked = summary.visa_marked if track == "visa" else summary.flight_marked
        return TrackerCounts(total=summary.total, marked=marked, pending=summary.total - marked)

    async def list_groups(
        self, *, search: str | None = None, page: int = 1, page_size: int = 24
    ) -> TrackerGroupList:
        self._page(page, page_size, 100)
        self._validate_filters("visa", "all", search)
        statement = self._group_query()
        normalized = " ".join((search or "").split())
        if normalized:
            statement = statement.where(
                or_(
                    ClientGroupModel.name.icontains(normalized, autoescape=True),
                    ClientGroupModel.destination.icontains(normalized, autoescape=True),
                )
            )
        total = int(
            await self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        groups = list(
            (
                await self.session.scalars(
                    statement.order_by(ClientGroupModel.created_at.desc(), ClientGroupModel.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        summary = await self._summary(groups)
        return TrackerGroupList(
            groups=[summary[group.id] for group in groups],
            total=total,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    def _passenger(
        passenger: PassportSubmissionModel, tracker: TravelTrackerModel | None
    ) -> TrackerPassenger:
        fields = field_values(passenger)
        return TrackerPassenger(
            id=passenger.id,
            full_name=full_name(passenger),
            given_name=text_value(fields.get("given_names")),
            surname=text_value(fields.get("surname")),
            passport_number=text_value(fields.get("passport_number")),
            nationality=text_value(fields.get("nationality")),
            gender=text_value(fields.get("sex")),
            date_of_birth=text_value(fields.get("date_of_birth")),
            date_of_expiry=text_value(fields.get("date_of_expiry")),
            email=passenger.client_email,
            phone=passenger.client_phone,
            departure_city=passenger.departure_city,
            submission_status=passenger.status,
            visa_applied=bool(tracker and tracker.visa_applied),
            flight_booked=bool(tracker and tracker.flight_booked),
            visa_updated_at=tracker.visa_updated_at if tracker else None,
            flight_updated_at=tracker.flight_updated_at if tracker else None,
        )

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
        self._page(page, page_size)
        group = await self._group(group_id)
        statement = self._filter(self._roster(group), track=track, status=status, search=search)
        total = int(
            await self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        rows = (
            await self.session.execute(
                statement.order_by(
                    func.lower(PassportSubmissionModel.client_name), PassportSubmissionModel.id
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        summary = (await self._summary([group]))[group.id]
        await record_sensitive_read(
            self.session,
            user=self.user,
            kind="group_view",
            agency_id=group.agency_id,
            entity_id=group.id,
            count=len(rows),
        )
        return TrackerWorkspace(
            group=summary,
            counts=self._counts(summary, track),
            passengers=[self._passenger(passenger, tracker) for passenger, tracker in rows],
            total=total,
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
        group = await self._group(group_id, lock=True)
        statement = self._roster(group)
        requested_ids = list(dict.fromkeys(body.passenger_ids or []))
        if body.selection is not None:
            statement = self._filter(
                statement,
                track=body.track,
                status=body.selection.status,
                search=body.selection.search,
            )
        else:
            statement = statement.where(PassportSubmissionModel.id.in_(requested_ids))
        rows = (
            await self.session.execute(
                statement.order_by(PassportSubmissionModel.id)
                .limit(MAX_EXPORT_ROWS + 1)
                .with_for_update(of=PassportSubmissionModel)
                .execution_options(populate_existing=True)
            )
        ).all()
        if len(rows) > MAX_EXPORT_ROWS:
            raise TravelTrackerError(
                status_code=422, detail="Narrow the selection to at most 20,000 passengers."
            )
        if body.selection is not None and len(rows) != body.expected_count:
            raise TravelTrackerError(
                status_code=409,
                detail="The passenger selection changed. Refresh the list and try again.",
            )
        if body.selection is None and len(rows) != len(requested_ids):
            raise TravelTrackerError(
                status_code=404,
                detail="One or more selected passengers were not found in this group.",
            )
        flag = "visa_applied" if body.track == "visa" else "flight_booked"
        now, changed = datetime.now(UTC), []
        for passenger, tracker in rows:
            if bool(tracker and getattr(tracker, flag)) == body.marked:
                continue
            if tracker is None:
                tracker = TravelTrackerModel(
                    passenger_id=passenger.id,
                    group_id=group.id,
                    agency_id=group.agency_id,
                    visa_applied=False,
                    flight_booked=False,
                )
                self.session.add(tracker)
            setattr(tracker, flag, body.marked)
            setattr(tracker, body.track + "_updated_at", now)
            setattr(tracker, body.track + "_updated_by", self.user.id)
            changed.append(passenger.id)
        if changed:
            await AuditLogRepository(self.session).record(
                action="travel_tracker.marks_changed",
                entity_type="client_group",
                entity_id=str(group.id),
                agency_id=group.agency_id,
                user_id=self.user.id,
                actor_email=self.user.email,
                metadata={
                    "track": body.track,
                    "marked": body.marked,
                    "updated_count": len(changed),
                    "passenger_ids": [str(value) for value in changed],
                },
            )
        await self.session.flush()
        summary = (await self._summary([group]))[group.id]
        result = TrackerMarkResponse(
            updated_count=len(changed),
            unchanged_count=len(rows) - len(changed),
            passenger_ids=[passenger.id for passenger, _ in rows],
            counts=self._counts(summary, body.track),
        )
        if commit:
            try:
                await self.session.commit()
            except Exception:
                await self.session.rollback()
                raise
        return result

    async def export(
        self,
        group_id: uuid.UUID,
        *,
        track: TrackerTrack = "visa",
        status: TrackerStatus = "all",
        search: str | None = None,
    ) -> tuple[bytes, str]:
        group = await self._group(group_id)
        statement = self._filter(self._roster(group), track=track, status=status, search=search)
        rows = (
            await self.session.execute(
                statement.order_by(
                    func.lower(PassportSubmissionModel.client_name), PassportSubmissionModel.id
                ).limit(MAX_EXPORT_ROWS + 1)
            )
        ).all()
        if len(rows) > MAX_EXPORT_ROWS:
            raise TravelTrackerError(
                status_code=422, detail="Narrow the export to at most 20,000 passengers."
            )
        try:
            content = await run_tracker_work(
                build_export, group, [(passenger, tracker) for passenger, tracker in rows]
            )
        except TrackerSpreadsheetError as exc:
            raise TravelTrackerError(status_code=422, detail=str(exc)) from exc
        await AuditLogRepository(self.session).record(
            action="travel_tracker.exported",
            entity_type="client_group",
            entity_id=str(group.id),
            agency_id=group.agency_id,
            user_id=self.user.id,
            metadata={"track": track, "status": status, "exported_count": len(rows)},
        )
        filename = re.sub(r"[^A-Za-z0-9._-]+", "-", group.name).strip("-.")[:80] or "group"
        return content, f"{filename}-{track}-{status}.xlsx"

    async def preview(
        self,
        group_id: uuid.UUID,
        *,
        content: bytes,
        filename: str,
        track: TrackerTrack = "visa",
        marked: bool = True,
    ) -> TrackerImportPreview:
        self._validate_filters(track, "all", None)
        group = await self._group(group_id)
        if len(content) > MAX_UPLOAD_BYTES:
            raise TravelTrackerError(status_code=413, detail="Upload a file smaller than 8 MB.")
        try:
            await run_tracker_work(malware_scanner_from_settings().scan, content)
            records = await run_tracker_work(read_rows, content, filename)
        except (TrackerSpreadsheetError, ImageValidationError) as exc:
            raise TravelTrackerError(status_code=422, detail=str(exc)) from exc
        rows = (await self.session.execute(self._roster(group).limit(MAX_EXPORT_ROWS + 1))).all()
        if len(rows) > MAX_EXPORT_ROWS:
            raise TravelTrackerError(
                status_code=422,
                detail="Spreadsheet matching supports groups up to 20,000 passengers.",
            )
        result = await run_tracker_work(
            match_rows, records, [passenger for passenger, _ in rows], track=track, marked=marked
        )
        await record_sensitive_read(
            self.session,
            user=self.user,
            kind="group_view",
            agency_id=group.agency_id,
            entity_id=group.id,
            count=len(rows),
        )
        return result
