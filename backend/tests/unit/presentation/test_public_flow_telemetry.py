from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError as PydanticValidationError

from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.observability.operational_events import OperationalEvent
from app.presentation.api.v1.routes.client_groups import (
    record_public_flow_telemetry,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    PublicFlowTelemetryRequest,
)


class _ActiveLink:
    async def execute(self, *, token: str) -> object:
        return {"token_present": bool(token)}


class _MissingLink:
    async def execute(self, *, token: str) -> object:
        raise EntityNotFoundError("Upload link", token)


class PublicFlowTelemetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_link_records_one_fixed_event_without_identifiers(
        self,
    ) -> None:
        body = PublicFlowTelemetryRequest(
            event="visa_photo_rejection",
            reason="eyewear_detected",
        )
        with patch(
            "app.presentation.api.v1.routes.client_groups."
            "record_operational_event"
        ) as record:
            response = await record_public_flow_telemetry(
                token="secret-upload-token",
                body=body,
                upload_session_id="bootstrap-12345678",
                use_case=_ActiveLink(),  # type: ignore[arg-type]
            )

        self.assertEqual(response.status_code, 204)
        record.assert_called_once_with(
            OperationalEvent.VISA_PHOTO_REJECTION,
            "eyewear_detected",
        )
        serialized_call = repr(record.call_args)
        self.assertNotIn("secret-upload-token", serialized_call)
        self.assertNotIn("bootstrap-12345678", serialized_call)

    async def test_invalid_or_inactive_link_is_not_a_telemetry_oracle(
        self,
    ) -> None:
        body = PublicFlowTelemetryRequest(
            event="public_flow",
            reason="recovery_missed",
        )
        with patch(
            "app.presentation.api.v1.routes.client_groups."
            "record_operational_event"
        ) as record:
            response = await record_public_flow_telemetry(
                token="unknown-token",
                body=body,
                upload_session_id="bootstrap-12345678",
                use_case=_MissingLink(),  # type: ignore[arg-type]
            )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        record.assert_not_called()

    async def test_reason_must_belong_to_the_selected_event(self) -> None:
        body = PublicFlowTelemetryRequest(
            event="passport_scanner_rejection",
            reason="eyewear_detected",
        )
        with self.assertRaises(HTTPException) as raised:
            await record_public_flow_telemetry(
                token="secret-upload-token",
                body=body,
                upload_session_id="bootstrap-12345678",
                use_case=_ActiveLink(),  # type: ignore[arg-type]
            )
        self.assertEqual(raised.exception.status_code, 400)

    async def test_session_identifier_is_strictly_validated(self) -> None:
        body = PublicFlowTelemetryRequest(
            event="public_flow",
            reason="connectivity_restored",
        )
        with self.assertRaises(HTTPException) as raised:
            await record_public_flow_telemetry(
                token="secret-upload-token",
                body=body,
                upload_session_id="contains spaces",
                use_case=_ActiveLink(),  # type: ignore[arg-type]
            )
        self.assertEqual(raised.exception.status_code, 400)

    def test_schema_rejects_server_only_event_and_extra_data(self) -> None:
        with self.assertRaises(PydanticValidationError):
            PublicFlowTelemetryRequest(
                event="staff_approval",  # type: ignore[arg-type]
                reason="approved",
            )
        with self.assertRaises(PydanticValidationError):
            PublicFlowTelemetryRequest.model_validate(
                {
                    "event": "public_flow",
                    "reason": "connectivity_lost",
                    "passport_number": "P1234567",
                }
            )


if __name__ == "__main__":
    unittest.main()
