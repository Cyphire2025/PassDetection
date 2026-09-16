"""Historical sync/access regression through HTTP and an isolated PostgreSQL DB."""

import os

import pytest

from tests.service_integration.test_fcm_dispatch_postgresql import pg_factory as pg_factory
from tests.unit.presentation.test_mobile_historical_access_sync import (
    test_current_revocation_is_denied_before_historical_projection as test_current_revocation_is_denied_before_historical_projection,
)
from tests.unit.presentation.test_mobile_historical_access_sync import (
    test_new_session_passes_historical_revokes_and_advances_without_rewriting_history as test_new_session_passes_historical_revokes_and_advances_without_rewriting_history,
)
from tests.unit.presentation.test_mobile_historical_access_sync import (
    test_projection_keeps_unrelated_or_unknown_revocations as test_projection_keeps_unrelated_or_unknown_revocations,
)
from tests.unit.presentation.test_mobile_historical_access_sync import (
    test_window_edit_invalidates_old_session_but_only_revokes_disabled_role as test_window_edit_invalidates_old_session_but_only_revokes_disabled_role,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"),
]


@pytest.fixture
async def db_session(pg_factory):
    async with pg_factory() as session:
        yield session
