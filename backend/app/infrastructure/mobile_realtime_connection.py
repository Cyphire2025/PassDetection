"""One bounded trip-coalescing queue for an authenticated realtime socket."""

from __future__ import annotations

import asyncio
import uuid

from app.application.mobile.realtime_authorization import MobileRealtimeAuthorization
from app.application.mobile.realtime_hints import MobileRealtimeHint
from app.infrastructure.mobile_realtime_contracts import MobileRealtimeConnectionClosed


class MobileRealtimeConnection:
    """A bounded, trip-coalescing queue owned by one authenticated socket."""

    def __init__(
        self,
        *,
        authorization: MobileRealtimeAuthorization,
        maximum_pending_trips: int,
    ) -> None:
        self.id = uuid.uuid4()
        self.authorization = authorization
        self._maximum_pending_trips = maximum_pending_trips
        self._pending: dict[uuid.UUID, MobileRealtimeHint] = {}
        self._wake = asyncio.Event()
        self.close_code: int | None = None

    @property
    def trip_ids(self) -> frozenset[uuid.UUID]:
        return self.authorization.trip_ids

    def offer(self, hint: MobileRealtimeHint) -> bool:
        if self.close_code is not None:
            return False
        previous = self._pending.get(hint.trip_id)
        if previous is not None:
            self._pending[hint.trip_id] = MobileRealtimeHint(
                agency_id=hint.agency_id,
                trip_id=hint.trip_id,
                cursor=max(previous.cursor, hint.cursor),
                invalidation=(
                    previous.invalidation if previous.invalidation == hint.invalidation else "all"
                ),
            )
            self._wake.set()
            return True
        if len(self._pending) >= self._maximum_pending_trips:
            # Disconnecting a slow consumer is safer than allowing unbounded
            # memory growth. Its durable cursor reconciles on reconnect.
            self.signal_close(1013)
            return False
        self._pending[hint.trip_id] = hint
        self._wake.set()
        return True

    async def next_hint(self) -> MobileRealtimeHint:
        while True:
            if self.close_code is not None:
                raise MobileRealtimeConnectionClosed()
            if self._pending:
                trip_id = next(iter(self._pending))
                hint = self._pending.pop(trip_id)
                if not self._pending:
                    self._wake.clear()
                return hint
            self._wake.clear()
            await self._wake.wait()

    def signal_close(self, code: int) -> None:
        self.close_code = code
        self._pending.clear()
        self._wake.set()
