"""Local session admission, tenant/trip membership and bounded fanout."""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from dataclasses import dataclass

from app.application.mobile.realtime_authorization import MobileRealtimeAuthorization
from app.application.mobile.realtime_hints import MobileRealtimeHint
from app.infrastructure.mobile_realtime_connection import MobileRealtimeConnection
from app.infrastructure.mobile_realtime_contracts import (
    MobileRealtimeCapacityError,
    MobileRealtimeConfig,
    RealtimeAvailability,
)


@dataclass(frozen=True, slots=True)
class RealtimeRegistrySnapshot:
    connections: tuple[MobileRealtimeConnection, ...]
    connection_lease_ids: tuple[uuid.UUID, ...]
    authorization_lease_ids: tuple[uuid.UUID, ...]


class RealtimeConnectionRegistry:
    def __init__(self, availability: RealtimeAvailability) -> None:
        self._availability = availability
        self._connection_lock = asyncio.Lock()
        self._connections: dict[uuid.UUID, MobileRealtimeConnection] = {}
        self._trip_index: dict[tuple[uuid.UUID, uuid.UUID], set[uuid.UUID]] = {}
        self._session_connection_counts: Counter[uuid.UUID] = Counter()
        self._leased_connection_ids: set[uuid.UUID] = set()
        self._authorization_reservation_ids: set[uuid.UUID] = set()
        self._authorization_lease_ids: set[uuid.UUID] = set()
        self._authenticating = 0
        self._delivered = 0
        self._dropped = 0
        self._authentication_rejections = 0
        self._connection_rejections = 0
        self._slow_consumer_disconnects = 0

    async def reserve_connection(
        self, authorization: MobileRealtimeAuthorization, config: MobileRealtimeConfig
    ) -> MobileRealtimeConnection:
        connection = MobileRealtimeConnection(
            authorization=authorization,
            maximum_pending_trips=config.max_pending_trips_per_connection,
        )
        async with self._connection_lock:
            if len(self._connections) >= config.max_connections:
                self._connection_rejections += 1
                raise MobileRealtimeCapacityError("Realtime connection limit reached")
            if (
                self._session_connection_counts[authorization.session_id]
                >= config.max_connections_per_session
            ):
                self._connection_rejections += 1
                raise MobileRealtimeCapacityError("Realtime session connection limit reached")
            # Reserve locally before awaiting Redis so concurrent calls cannot
            # race past the process-local safety rails. The connection is not
            # indexed for fanout until its global lease succeeds.
            self._connections[connection.id] = connection
            self._session_connection_counts[authorization.session_id] += 1
        return connection

    async def activate_connection(self, connection: MobileRealtimeConnection) -> bool:
        async with self._connection_lock:
            if (
                not self._availability.accepting_connections
                or connection.id not in self._connections
            ):
                return False
            self._leased_connection_ids.add(connection.id)
            self._index_connection(connection)
        return True

    async def reserve_authorization(self, config: MobileRealtimeConfig) -> uuid.UUID:
        async with self._connection_lock:
            if len(self._connections) >= config.max_connections:
                self._connection_rejections += 1
                raise MobileRealtimeCapacityError("Realtime connection limit reached")
            if self._authenticating >= config.max_authenticating_connections:
                self._authentication_rejections += 1
                raise MobileRealtimeCapacityError("Realtime authentication capacity reached")
            reservation_id = uuid.uuid4()
            self._authenticating += 1
            self._authorization_reservation_ids.add(reservation_id)
        return reservation_id

    async def activate_authorization(self, reservation_id: uuid.UUID) -> bool:
        async with self._connection_lock:
            if (
                not self._availability.accepting_connections
                or reservation_id not in self._authorization_reservation_ids
            ):
                return False
            self._authorization_lease_ids.add(reservation_id)
        return True

    def reject_connection(self) -> None:
        self._connection_rejections += 1

    def reject_authorization(self) -> None:
        self._authentication_rejections += 1

    def connection_is_leased(self, connection_id: uuid.UUID) -> bool:
        return connection_id in self._leased_connection_ids

    async def lease_snapshot(self) -> tuple[tuple[uuid.UUID, ...], tuple[uuid.UUID, ...]]:
        async with self._connection_lock:
            return tuple(self._leased_connection_ids), tuple(self._authorization_lease_ids)

    async def has_missing_active_leases(
        self, connections: set[uuid.UUID], authorizations: set[uuid.UUID]
    ) -> bool:
        async with self._connection_lock:
            active_missing_connections = connections & self._leased_connection_ids
            active_missing_authorizations = authorizations & self._authorization_lease_ids
        return bool(active_missing_connections or active_missing_authorizations)

    async def clear(self) -> RealtimeRegistrySnapshot:
        async with self._connection_lock:
            connections = tuple(self._connections.values())
            connection_lease_ids = tuple(self._leased_connection_ids)
            authorization_lease_ids = tuple(self._authorization_lease_ids)
            self._connections.clear()
            self._trip_index.clear()
            self._session_connection_counts.clear()
            self._leased_connection_ids.clear()
            self._authorization_reservation_ids.clear()
            self._authorization_lease_ids.clear()
            self._authenticating = 0
        return RealtimeRegistrySnapshot(connections, connection_lease_ids, authorization_lease_ids)

    def snapshot(self) -> dict[str, int]:
        return {
            "connections": len(self._connections),
            "authenticating": self._authenticating,
            "leased_connections": len(self._leased_connection_ids),
            "leased_authenticating": len(self._authorization_lease_ids),
            "delivered": self._delivered,
            "dropped": self._dropped,
            "authentication_rejections": self._authentication_rejections,
            "connection_rejections": self._connection_rejections,
            "slow_consumer_disconnects": self._slow_consumer_disconnects,
        }

    async def _remove_authorization_reservation(self, reservation_id: uuid.UUID) -> bool:
        async with self._connection_lock:
            if reservation_id not in self._authorization_reservation_ids:
                return False
            self._authorization_reservation_ids.remove(reservation_id)
            self._authorization_lease_ids.discard(reservation_id)
            self._authenticating -= 1
            return True

    async def _remove_connection(
        self,
        connection: MobileRealtimeConnection,
        *,
        close_code: int,
    ) -> bool:
        async with self._connection_lock:
            removed = self._connections.pop(connection.id, None)
            if removed is None:
                return False
            self._leased_connection_ids.discard(connection.id)
            self._deindex_connection(removed)
            session_id = removed.authorization.session_id
            self._session_connection_counts[session_id] -= 1
            if self._session_connection_counts[session_id] <= 0:
                del self._session_connection_counts[session_id]
        connection.signal_close(close_code)
        return True

    async def update_authorization(
        self,
        connection: MobileRealtimeConnection,
        authorization: MobileRealtimeAuthorization,
    ) -> bool:
        async with self._connection_lock:
            active = self._connections.get(connection.id)
            if active is None:
                return False
            if not active.authorization.same_authentication_boundary(authorization):
                active.signal_close(4401)
                return False
            self._deindex_connection(active)
            active.authorization = authorization
            self._index_connection(active)
            return True

    async def fanout(self, hint: MobileRealtimeHint) -> int:
        async with self._connection_lock:
            ids = tuple(self._trip_index.get((hint.agency_id, hint.trip_id), ()))
            connections = tuple(
                connection
                for connection_id in ids
                if (connection := self._connections.get(connection_id)) is not None
            )
        delivered = 0
        for connection in connections:
            was_open = connection.close_code is None
            if connection.offer(hint):
                delivered += 1
            else:
                self._dropped += 1
                if was_open and connection.close_code == 1013:
                    self._slow_consumer_disconnects += 1
        self._delivered += delivered
        return delivered

    def _index_connection(self, connection: MobileRealtimeConnection) -> None:
        agency_id = connection.authorization.agency_id
        for trip_id in connection.trip_ids:
            self._trip_index.setdefault((agency_id, trip_id), set()).add(connection.id)

    def _deindex_connection(self, connection: MobileRealtimeConnection) -> None:
        agency_id = connection.authorization.agency_id
        for trip_id in connection.trip_ids:
            key = (agency_id, trip_id)
            ids = self._trip_index.get(key)
            if ids is None:
                continue
            ids.discard(connection.id)
            if not ids:
                self._trip_index.pop(key, None)
