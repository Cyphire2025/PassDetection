"""Creation-time passenger capacity contract for mobile-enabled group data."""

from __future__ import annotations

import uuid
from typing import Protocol


class GroupPassengerCapacityGuard(Protocol):
    """Serialize group creation and reject additions beyond the published quota."""

    async def lock_group(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> None: ...

    async def assert_available(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        additional_passengers: int,
    ) -> None: ...


__all__ = ["GroupPassengerCapacityGuard"]
