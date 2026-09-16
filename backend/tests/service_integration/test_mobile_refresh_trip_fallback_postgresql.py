"""Exercise refresh fallback and its row-lock query against isolated PostgreSQL."""

import os

import pytest

from tests.service_integration.test_fcm_dispatch_postgresql import pg_factory as pg_factory
from tests.unit.presentation.test_mobile_refresh_trip_fallback import (
    test_fallback_does_not_bypass_session_or_identity_revocation as test_fallback_does_not_bypass_session_or_identity_revocation,
)
from tests.unit.presentation.test_mobile_refresh_trip_fallback import (
    test_refresh_keeps_current_authorized_selection as test_refresh_keeps_current_authorized_selection,
)
from tests.unit.presentation.test_mobile_refresh_trip_fallback import (
    test_refresh_never_selects_an_unavailable_or_unproven_trip as test_refresh_never_selects_an_unavailable_or_unproven_trip,
)
from tests.unit.presentation.test_mobile_refresh_trip_fallback import (
    test_refresh_of_removed_selected_trip_uses_existing_binding_and_invalidates_old_bearer as test_refresh_of_removed_selected_trip_uses_existing_binding_and_invalidates_old_bearer,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.service_integration,
    pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"),
]


@pytest.fixture
async def db_session(pg_factory):
    async with pg_factory() as session:
        yield session
