"""Client group visibility, retention and deletion transitions."""

from __future__ import annotations

from datetime import timedelta

from app.domain.entities.client_group_state import ClientGroupState
from app.domain.entities.enums import GroupStatus
from app.domain.entities.factories import _utcnow
from app.domain.exceptions.exceptions import ValidationError


class ClientGroupLifecycle(ClientGroupState):
    """Change lifecycle visibility and schedule retained passport deletion."""

    def is_active(self) -> bool:
        """True for an active lifecycle; public access also checks the import mode."""
        return self.status == GroupStatus.ACTIVE

    def schedule_passport_purge(self, retention_days: int) -> None:
        """Persist the exact policy-derived date for later hold-aware deletion."""

        if not 1 <= retention_days <= 3650:
            raise ValidationError(
                "Passport retention must be between 1 and 3650 days.",
                field="passport_data_retention_days",
            )
        anchor = self.deleted_at or self.closed_at
        self.passport_purge_at = (
            anchor + timedelta(days=retention_days) if anchor is not None else None
        )
        self.passport_retention_days_applied = retention_days if anchor is not None else None

    def close(self, *, passport_retention_days: int | None = None) -> None:
        """Close the group so no more uploads are accepted."""
        self.status = GroupStatus.CLOSED
        self.closed_at = _utcnow()
        if passport_retention_days is not None:
            self.schedule_passport_purge(passport_retention_days)

    def archive(self, *, passport_retention_days: int | None = None) -> None:
        """Archive the group so it is hidden from active workflows."""
        self.status = GroupStatus.ARCHIVED
        self.closed_at = self.closed_at or _utcnow()
        if passport_retention_days is not None and self.passport_purge_at is None:
            self.schedule_passport_purge(passport_retention_days)

    def restore(self) -> None:
        """Reopen a closed link or restore an archived or retained deleted group."""
        self.status = GroupStatus.ACTIVE
        self.closed_at = None
        self.deleted_at = None
        self.passport_purge_at = None
        self.passport_retention_days_applied = None
        self.deleted_passport_count = 0
        self.deletion_retained_records = False

    def mark_deleted(
        self,
        *,
        passport_count: int,
        retain_records: bool,
        passport_retention_days: int | None = None,
    ) -> None:
        """Hide a group from workflows while preserving deletion audit metadata."""
        self.status = GroupStatus.DELETED
        self.closed_at = self.closed_at or _utcnow()
        self.deleted_at = _utcnow()
        self.deleted_passport_count = passport_count
        self.deletion_retained_records = retain_records
        if retain_records and passport_retention_days is not None:
            self.schedule_passport_purge(passport_retention_days)
        elif not retain_records:
            self.passport_purge_at = None
            self.passport_retention_days_applied = None
