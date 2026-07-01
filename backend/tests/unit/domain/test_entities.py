"""
Test: Domain Entities
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.entities.entities import (
    Agency,
    PassportProcessingStatus,
    PassportSubmission,
    ClientGroup,
    GroupStatus,
    User,
    UserRole,
)


class TestUserEntity:
    def test_create_user_lowercases_email(self) -> None:
        user = User.create(
            email="TEST@EXAMPLE.COM",
            hashed_password="hashed",
            full_name="Test User",
            role=UserRole.AGENCY_STAFF,
        )
        assert user.email == "test@example.com"

    def test_super_admin_can_manage_any_agency(self) -> None:
        user = User.create(
            email="admin@example.com",
            hashed_password="hashed",
            full_name="Admin",
            role=UserRole.SUPER_ADMIN,
        )
        assert user.can_manage_agency(uuid.uuid4()) is True

    def test_agency_admin_can_only_manage_own_agency(self) -> None:
        own_agency = uuid.uuid4()
        other_agency = uuid.uuid4()
        user = User.create(
            email="admin@agency.com",
            hashed_password="hashed",
            full_name="Agency Admin",
            role=UserRole.AGENCY_ADMIN,
            agency_id=own_agency,
        )
        assert user.can_manage_agency(own_agency) is True
        assert user.can_manage_agency(other_agency) is False

    def test_deactivate_user(self) -> None:
        user = User.create(
            email="user@example.com",
            hashed_password="hashed",
            full_name="User",
            role=UserRole.AGENCY_STAFF,
        )
        assert user.is_active is True
        user.deactivate()
        assert user.is_active is False


class TestClientGroupEntity:
    def _make_link(self) -> ClientGroup:
        return ClientGroup.create(
            token="test-token-abc123",
            agency_id=uuid.uuid4(),
            name="Test Group",
            created_by_user_id=uuid.uuid4(),
        )

    def test_active_link_is_usable(self) -> None:
        link = self._make_link()
        assert link.is_active() is True

    def test_expired_link_is_not_usable(self) -> None:
        link = self._make_link()
        link.close()
        assert link.is_active() is False

    def test_used_link_is_not_usable(self) -> None:
        link = self._make_link()
        link.close()
        assert link.is_active() is False
        assert link.status == GroupStatus.CLOSED

    def test_revoke_link(self) -> None:
        link = self._make_link()
        link.archive()
        assert link.status == GroupStatus.ARCHIVED
        assert link.is_active() is False


class TestPassportSubmissionEntity:
    def _make_submission(self) -> PassportSubmission:
        return PassportSubmission.create(
            group_id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            client_name="Jane Smith",
            client_email="jane@example.com",
            image_s3_key="uploads/passports/abc123.jpg",
        )

    def test_initial_status_is_uploaded(self) -> None:
        sub = self._make_submission()
        assert sub.status == PassportProcessingStatus.UPLOADED

    def test_confirm_sets_confirmed_fields(self) -> None:
        sub = self._make_submission()
        sub.mark_processing()
        sub.mark_review_required(
            extracted_fields={"surname": "SMITH", "given_names": "JANE"},
            confidence=0.92,
        )
        sub.confirm(confirmed_fields={"surname": "SMITH", "given_names": "JANE"})
        assert sub.status == PassportProcessingStatus.CONFIRMED
        assert sub.confirmed_fields is not None
        assert sub.confirmed_at is not None

    def test_mark_failed(self) -> None:
        sub = self._make_submission()
        sub.mark_failed("Image too blurry")
        assert sub.status == PassportProcessingStatus.FAILED
        assert sub.error_message == "Image too blurry"
