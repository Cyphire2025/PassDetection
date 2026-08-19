import type { MobileRole } from '@/core/auth/types';
import { DEFAULT_TRIP_TIME_ZONE } from '@/core/localization/time-zone';

import {
  SnapshotContractError,
  assertSameSnapshotFence,
  snapshotCheckpointFromPage,
  validateSnapshotDescriptor,
} from '../snapshot-rebase-contract';

const TRIP_ID = '11111111-1111-4111-8111-111111111111';
const SERVER_TIME = '2030-01-01T00:00:00.000Z';

function descriptor(role: MobileRole = 'passenger', generation = 3) {
  const trip = `/api/v1/mobile/trips/${TRIP_ID}`;
  const coordinator = `/api/v1/mobile/coordinator/groups/${TRIP_ID}`;
  const manager = `/api/v1/mobile/manager/groups/${TRIP_ID}`;
  return {
    strategy: 'full_rebase' as const,
    trip: {
      id: TRIP_ID,
      name: 'Enterprise trip',
      destination: null,
      travel_date: null,
      return_date: null,
      timezone: DEFAULT_TRIP_TIME_ZONE,
      role,
      access_generation: generation,
      itinerary_version: 2,
      common_document_version: 4,
      announcement_version: 5,
    },
    baseline_cursor: 12_345,
    access_generation: generation,
    server_time: SERVER_TIME,
    access_expires_at: '2030-02-01T00:00:00.000Z',
    versions: {
      manifest: 7,
      itinerary: 2,
      common_documents: 4,
      personal_documents: role === 'passenger' ? 8 : 0,
      announcements: 5,
      rooming: 2,
      meals: 1,
      qr: 3,
      readiness: role === 'client_manager' ? 2 : 0,
      roster: role === 'coordinator' || role === 'client_manager' ? 7 : 0,
    },
    resources: {
      manifest: `${trip}/manifest`,
      itinerary: `${trip}/itinerary`,
      announcements: `${trip}/announcements`,
      common_documents: `${trip}/common-documents`,
      personal_documents: role === 'passenger' ? `${trip}/documents` : null,
      room: role === 'passenger' ? `${trip}/room` : null,
      meals: role === 'passenger' ? `${trip}/meals` : null,
      qr: role === 'passenger' ? `${trip}/qr` : null,
      readiness: role === 'client_manager' ? `${manager}/readiness` : null,
      roster: role === 'coordinator'
        ? `${coordinator}/passengers`
        : role === 'client_manager'
          ? `${manager}/passengers`
          : null,
      attendance_sessions: role === 'coordinator'
        ? `${coordinator}/attendance/sessions`
        : role === 'client_manager'
          ? `${manager}/attendance/sessions`
          : null,
      sync_changes: `/api/v1/mobile/sync/changes?trip_id=${TRIP_ID}`,
      acknowledge: '/api/v1/mobile/sync/ack',
    },
    resource_counts: {
      announcements: 4,
      common_documents: 6,
      personal_documents: role === 'passenger' ? 3 : null,
      roster: role === 'coordinator' || role === 'client_manager' ? 8_500 : null,
      attendance_sessions: role === 'coordinator' || role === 'client_manager' ? 120 : null,
    },
    max_incremental_changes: 10_000,
    max_group_passengers: 10_000,
    max_attendance_sessions_per_group: 10_000,
  };
}

function boundary(role: MobileRole = 'passenger') {
  return {
    checkpointCursor: 12_345,
    committedCursor: 10,
    currentAccessGeneration: 3,
    role,
    tripId: TRIP_ID,
  };
}

test('accepts only the exact isolated snapshot checkpoint shape', () => {
  const page = {
    changes: [{
      sequence: 12_345,
      group_id: TRIP_ID,
      entity_type: 'snapshot_rebase',
      entity_id: null,
      operation: 'upsert' as const,
      version: 7,
      occurred_at: SERVER_TIME,
      payload: {
        resource_path: `/api/v1/mobile/sync/snapshot?trip_id=${TRIP_ID}`,
      },
    }],
    next_cursor: 12_345,
    has_more: false,
  };

  expect(snapshotCheckpointFromPage(page, TRIP_ID)).toEqual({
    checkpointCursor: 12_345,
    resourcePath: `/api/v1/mobile/sync/snapshot?trip_id=${TRIP_ID}`,
  });
  expect(() => snapshotCheckpointFromPage({
    ...page,
    has_more: true,
  }, TRIP_ID)).toThrow(SnapshotContractError);
  expect(() => snapshotCheckpointFromPage({
    ...page,
    changes: [{
      ...page.changes[0]!,
      payload: {
        resource_path: `/api/v1/mobile/sync/snapshot?trip_id=${TRIP_ID}`,
        injected: true,
      },
    }],
  }, TRIP_ID)).toThrow(SnapshotContractError);
});

test('rejects cross-role paths, duplicate-generation disagreement, and stale generation', () => {
  const crossRole = descriptor('passenger');
  crossRole.resources.roster = `/api/v1/mobile/coordinator/groups/${TRIP_ID}/passengers`;
  expect(() => validateSnapshotDescriptor(crossRole, boundary()))
    .toThrow('invalid role resource map');

  const duplicateGeneration = descriptor('passenger');
  duplicateGeneration.trip.access_generation = 4;
  expect(() => validateSnapshotDescriptor(duplicateGeneration, boundary()))
    .toThrow('workspace boundary');

  expect(() => validateSnapshotDescriptor(descriptor('passenger', 2), boundary()))
    .toThrow('access generation was stale');
});

test('rejects expired leases and regressing baselines', () => {
  const expired = descriptor();
  expired.access_expires_at = SERVER_TIME;
  expect(() => validateSnapshotDescriptor(expired, boundary()))
    .toThrow('expired or invalid');

  const regressing = descriptor();
  regressing.baseline_cursor = 12_344;
  expect(() => validateSnapshotDescriptor(regressing, boundary()))
    .toThrow('regress synchronized state');
});

test('S1 and S2 compare every authoritative version', () => {
  const first = descriptor();
  const second = descriptor();
  second.versions.qr += 1;
  expect(() => assertSameSnapshotFence(first, second)).toThrow('snapshot changed');

  const countChanged = descriptor();
  countChanged.resource_counts.announcements += 1;
  expect(() => assertSameSnapshotFence(first, countChanged)).toThrow('snapshot changed');
});

test('rejects role-inapplicable counts and counts above an advertised capacity', () => {
  const crossRoleCount = descriptor('passenger');
  crossRoleCount.resource_counts.roster = 1;
  expect(() => validateSnapshotDescriptor(crossRoleCount, boundary()))
    .toThrow('role boundary');

  const overCapacity = descriptor('coordinator');
  overCapacity.resource_counts.roster = 10_001;
  expect(() => validateSnapshotDescriptor(overCapacity, boundary('coordinator')))
    .toThrow('advertised capacity');
});
