from __future__ import annotations

import unittest
import uuid
from unittest.mock import AsyncMock

from fastapi import HTTPException, Response
from pydantic import ValidationError

from app.presentation.api.v1.routes.passports import reconcile_passport_upload
from app.presentation.api.v1.schemas.passport_schemas import (
    ReconcilePassportUploadRequest,
)


class PassportUploadReconciliationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_only_submission_id_and_disables_caching(self) -> None:
        attempt_key = "upload-attempt-12345678-abcdef-123456"
        submission_id = uuid.uuid4()
        use_case = AsyncMock()
        use_case.execute.return_value = submission_id
        response = Response()

        result = await reconcile_passport_upload(
            token="active-upload-link-token",
            body=ReconcilePassportUploadRequest(
                upload_idempotency_key=attempt_key,
            ),
            response=response,
            upload_session_id=attempt_key,
            use_case=use_case,
        )

        self.assertEqual(result.model_dump(), {"submission_id": submission_id})
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        use_case.execute.assert_awaited_once_with(
            token="active-upload-link-token",
            upload_idempotency_key=attempt_key,
        )

    async def test_unknown_wrong_and_expired_links_share_empty_response_shape(
        self,
    ) -> None:
        attempt_key = "upload-attempt-12345678-abcdef-123456"
        use_case = AsyncMock()
        use_case.execute.return_value = None

        for token in (
            "unknown-upload-link-token",
            "wrong-upload-link-token",
            "expired-upload-link-token",
        ):
            result = await reconcile_passport_upload(
                token=token,
                body=ReconcilePassportUploadRequest(
                    upload_idempotency_key=attempt_key,
                ),
                response=Response(),
                upload_session_id=attempt_key,
                use_case=use_case,
            )
            self.assertEqual(result.model_dump(), {"submission_id": None})

    async def test_mismatched_header_is_rejected_before_lookup(self) -> None:
        use_case = AsyncMock()

        with self.assertRaises(HTTPException) as raised:
            await reconcile_passport_upload(
                token="active-upload-link-token",
                body=ReconcilePassportUploadRequest(
                    upload_idempotency_key=(
                        "upload-attempt-12345678-abcdef-123456"
                    ),
                ),
                response=Response(),
                upload_session_id="different-attempt-12345678-abcdef-123456",
                use_case=use_case,
            )

        self.assertEqual(raised.exception.status_code, 400)
        use_case.execute.assert_not_awaited()

    def test_request_rejects_unbounded_unsafe_or_extra_input(self) -> None:
        for payload in (
            {"upload_idempotency_key": "short"},
            {"upload_idempotency_key": "unsafe key value"},
            {"upload_idempotency_key": "x" * 129},
            {
                "upload_idempotency_key": (
                    "upload-attempt-12345678-abcdef-123456"
                ),
                "client_name": "Must not be accepted",
            },
        ):
            with self.assertRaises(ValidationError):
                ReconcilePassportUploadRequest.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
