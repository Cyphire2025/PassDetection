"""Route contract for serialized and idempotent staff passport approval."""

from __future__ import annotations

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Response
from pydantic import ValidationError as PydanticValidationError

from app.application.use_cases.passports.staff_approve_passport_use_case import (
    StaffApprovalResult,
)
from app.domain.entities.entities import StaffApprovalOutcome
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    StaffApprovalStaleError,
    StaffApprovalUnavailableError,
)
from app.presentation.api.v1.routes.passports import staff_approve_passport
from app.presentation.api.v1.schemas.passport_schemas import (
    StaffApprovePassportRequest,
)


def _approval_result(
    *,
    outcome: StaffApprovalOutcome = StaffApprovalOutcome.APPROVED,
) -> StaffApprovalResult:
    submission = SimpleNamespace(
        id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        status="staff_approved",
        extraction_revision=8,
        post_submission_verification_revision=3,
    )
    return StaffApprovalResult(
        submission=submission,  # type: ignore[arg-type]
        outcome=outcome,
        previous_status=(
            "needs_review"
            if outcome is StaffApprovalOutcome.APPROVED
            else "staff_approved"
        ),
        corrected_field_names=(
            ("passport_number",)
            if outcome is StaffApprovalOutcome.APPROVED
            else ()
        ),
        review_reason="Visual mismatch confirmed.",
    )


class StaffApprovalRequestSchemaTests(unittest.TestCase):
    def test_revision_is_required_and_reason_is_optional_but_bounded(self) -> None:
        request = StaffApprovePassportRequest(
            confirmed_fields={"passport_number": "P1234567"},
            expected_extraction_revision=7,
            review_reason="Visual mismatch confirmed.",
        )
        self.assertEqual(request.expected_extraction_revision, 7)

        with self.assertRaises(PydanticValidationError):
            StaffApprovePassportRequest(expected_extraction_revision=-1)
        with self.assertRaises(PydanticValidationError):
            StaffApprovePassportRequest(
                expected_extraction_revision=7,
                review_reason="x" * 241,
            )
        with self.assertRaises(PydanticValidationError):
            StaffApprovePassportRequest()


class StaffApprovalRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.submission_id = uuid.uuid4()
        self.current_user = SimpleNamespace(
            id=uuid.uuid4(),
            full_name="Agency Reviewer",
        )
        self.existing = SimpleNamespace(
            id=self.submission_id,
            group_id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
        )
        self.get_use_case = SimpleNamespace(
            execute=AsyncMock(return_value=self.existing)
        )
        self.policy = SimpleNamespace(
            require_staff_approve_passport=AsyncMock()
        )
        self.session = AsyncMock()

    async def test_first_approval_commits_audit_and_qr_once_without_pii(self) -> None:
        approval = _approval_result()
        approve_use_case = SimpleNamespace(
            execute=AsyncMock(return_value=approval)
        )
        audit_repository = SimpleNamespace(record=AsyncMock())
        ensure_qr = AsyncMock()
        response = Response()
        expected_response = object()
        events: list[str] = []
        self.session.commit.side_effect = lambda: events.append("commit")

        async def build_response(result, *, session):  # type: ignore[no-untyped-def]
            self.assertIs(result, approval.submission)
            self.assertIs(session, self.session)
            self.assertIn("commit", events)
            events.append("response")
            return expected_response

        with (
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review.AuthorizationPolicy',
                return_value=self.policy,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review.AuditLogRepository',
                return_value=audit_repository,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review._ensure_submission_qr',
                new=ensure_qr,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review._response_from_dto',
                new=build_response,
            ),
        ):
            result = await staff_approve_passport(
                submission_id=self.submission_id,
                body=StaffApprovePassportRequest(
                    confirmed_fields={"passport_number": "SECRET-P1234567"},
                    expected_extraction_revision=7,
                    review_reason="  Visual mismatch confirmed. ",
                ),
                response=response,
                _csrf=None,
                current_user=self.current_user,
                get_use_case=self.get_use_case,
                approve_use_case=approve_use_case,
                session=self.session,
            )

        self.assertIs(result, expected_response)
        self.policy.require_staff_approve_passport.assert_awaited_once_with(
            self.current_user,
            self.existing,
        )
        approve_use_case.execute.assert_awaited_once_with(
            self.submission_id,
            reviewer_id=self.current_user.id,
            reviewer_name=self.current_user.full_name,
            confirmed_fields={"passport_number": "SECRET-P1234567"},
            expected_extraction_revision=7,
            review_reason="  Visual mismatch confirmed. ",
        )
        audit_repository.record.assert_awaited_once()
        audit_call = audit_repository.record.await_args.kwargs
        self.assertEqual(audit_call["user_id"], self.current_user.id)
        self.assertEqual(
            audit_call["metadata"]["corrected_field_names"],
            ["passport_number"],
        )
        self.assertEqual(audit_call["metadata"]["prior_status"], "needs_review")
        self.assertEqual(audit_call["metadata"]["new_status"], "staff_approved")
        self.assertEqual(audit_call["metadata"]["outcome"], "approved")
        self.assertNotIn("SECRET-P1234567", repr(audit_call["metadata"]))
        self.assertNotIn("confirmed_fields", audit_call["metadata"])
        ensure_qr.assert_awaited_once_with(
            self.session,
            approval.submission.id,
            self.current_user.id,
        )
        self.session.commit.assert_awaited_once()
        self.assertEqual(response.headers["X-Staff-Approval-Outcome"], "approved")
        self.assertEqual(response.headers["X-Staff-Approval-Revision"], "8")
        self.assertEqual(events, ["commit", "response"])

    async def test_network_retry_returns_already_approved_without_side_effects(self) -> None:
        approval = _approval_result(
            outcome=StaffApprovalOutcome.ALREADY_APPROVED
        )
        approve_use_case = SimpleNamespace(
            execute=AsyncMock(return_value=approval)
        )
        audit_repository = SimpleNamespace(record=AsyncMock())
        ensure_qr = AsyncMock()
        response = Response()
        expected_response = object()

        with (
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review.AuthorizationPolicy',
                return_value=self.policy,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review.AuditLogRepository',
                return_value=audit_repository,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review._ensure_submission_qr',
                new=ensure_qr,
            ),
            patch(
                'app.presentation.api.v1.routes.passport_routes.submission_review._response_from_dto',
                new=AsyncMock(return_value=expected_response),
            ),
        ):
            result = await staff_approve_passport(
                submission_id=self.submission_id,
                body=StaffApprovePassportRequest(
                    confirmed_fields={"passport_number": "P1234567"},
                    expected_extraction_revision=7,
                ),
                response=response,
                _csrf=None,
                current_user=self.current_user,
                get_use_case=self.get_use_case,
                approve_use_case=approve_use_case,
                session=self.session,
            )

        self.assertIs(result, expected_response)
        audit_repository.record.assert_not_awaited()
        ensure_qr.assert_not_awaited()
        self.session.commit.assert_awaited_once()
        self.assertEqual(
            response.headers["X-Staff-Approval-Outcome"],
            "already_approved",
        )

    async def test_stale_and_unavailable_states_return_typed_409(self) -> None:
        cases = (
            (
                StaffApprovalStaleError(
                    expected_revision=6,
                    current_revision=8,
                ),
                "STAFF_APPROVAL_STALE",
                ("current_revision", 8),
            ),
            (
                StaffApprovalUnavailableError(current_status="ai_approved"),
                "STAFF_APPROVAL_UNAVAILABLE",
                ("current_status", "ai_approved"),
            ),
        )
        for exception, expected_code, detail in cases:
            with self.subTest(code=expected_code):
                approve_use_case = SimpleNamespace(
                    execute=AsyncMock(side_effect=exception)
                )
                with patch(
                    'app.presentation.api.v1.routes.passport_routes.submission_review.AuthorizationPolicy',
                    return_value=self.policy,
                ):
                    result = await staff_approve_passport(
                        submission_id=self.submission_id,
                        body=StaffApprovePassportRequest(
                            expected_extraction_revision=6
                        ),
                        response=Response(),
                        _csrf=None,
                        current_user=self.current_user,
                        get_use_case=self.get_use_case,
                        approve_use_case=approve_use_case,
                        session=self.session,
                    )

                self.assertEqual(result.status_code, 409)
                payload = json.loads(result.body)
                self.assertEqual(payload["error"]["code"], expected_code)
                self.assertEqual(
                    payload["error"]["details"][detail[0]],
                    detail[1],
                )
                self.assertEqual(result.headers["Cache-Control"], "no-store")
                self.session.commit.assert_not_awaited()
                self.session.rollback.assert_awaited_once()
                self.session.reset_mock()

    async def test_unauthorized_user_never_reaches_locked_approval(self) -> None:
        self.policy.require_staff_approve_passport.side_effect = (
            AuthorizationError("You cannot approve this passport submission")
        )
        approve_use_case = SimpleNamespace(execute=AsyncMock())

        with patch(
            'app.presentation.api.v1.routes.passport_routes.submission_review.AuthorizationPolicy',
            return_value=self.policy,
        ):
            with self.assertRaises(HTTPException) as raised:
                await staff_approve_passport(
                    submission_id=self.submission_id,
                    body=StaffApprovePassportRequest(
                        expected_extraction_revision=7,
                    ),
                    response=Response(),
                    _csrf=None,
                    current_user=self.current_user,
                    get_use_case=self.get_use_case,
                    approve_use_case=approve_use_case,
                    session=self.session,
                )

        self.assertEqual(raised.exception.status_code, 403)
        approve_use_case.execute.assert_not_awaited()
        self.session.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
