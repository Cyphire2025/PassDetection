import { z } from 'zod';

import type {
  MobileResourceVersions,
  SyncSnapshot,
  SyncPageSchema,
} from '@/core/api/contracts';
import type { MobileRole } from '@/core/auth/types';

export const SNAPSHOT_RESOURCE_NAMES = [
  'manifest',
  'itinerary',
  'announcements',
  'common_documents',
  'personal_documents',
  'room',
  'meals',
  'qr',
  'readiness',
  'roster',
  'attendance_sessions',
] as const;

export type SnapshotResourceName = (typeof SNAPSHOT_RESOURCE_NAMES)[number];
type SyncPage = z.infer<typeof SyncPageSchema>;

export class SnapshotContractError extends Error {
  readonly code = 'SNAPSHOT_CONTRACT_INVALID';

  constructor(message: string) {
    super(message);
    this.name = 'SnapshotContractError';
  }
}

export class SnapshotFenceChangedError extends Error {
  readonly code = 'SNAPSHOT_FENCE_CHANGED';

  constructor() {
    super('The snapshot changed while its metadata was being staged.');
    this.name = 'SnapshotFenceChangedError';
  }
}

export type SnapshotCheckpoint = Readonly<{
  checkpointCursor: number;
  resourcePath: string;
}>;

export type SnapshotValidationBoundary = Readonly<{
  checkpointCursor: number;
  committedCursor: number;
  currentAccessGeneration: number;
  role: MobileRole;
  tripId: string;
}>;

function expectedResourceMap(tripId: string, role: MobileRole): SyncSnapshot['resources'] {
  const trip = `/api/v1/mobile/trips/${tripId}`;
  const coordinator = `/api/v1/mobile/coordinator/groups/${tripId}`;
  const manager = `/api/v1/mobile/manager/groups/${tripId}`;
  return {
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
    sync_changes: `/api/v1/mobile/sync/changes?trip_id=${tripId}`,
    acknowledge: '/api/v1/mobile/sync/ack',
  };
}

export function mobileApiPath(resourcePath: string): string {
  if (!resourcePath.startsWith('/api/v1/mobile/') || resourcePath.includes('://')) {
    throw new SnapshotContractError('The snapshot resource path was invalid.');
  }
  return resourcePath.slice('/api/v1'.length);
}

export function snapshotCheckpointFromPage(
  page: SyncPage,
  tripId: string,
): SnapshotCheckpoint | null {
  const checkpoints = page.changes.filter((change) => change.entity_type === 'snapshot_rebase');
  if (checkpoints.length === 0) return null;
  if (checkpoints.length !== 1 || page.changes.length !== 1 || page.has_more) {
    throw new SnapshotContractError('The snapshot checkpoint page was malformed.');
  }
  const checkpoint = checkpoints[0];
  if (
    !checkpoint
    || checkpoint.group_id !== tripId
    || checkpoint.entity_id !== null
    || checkpoint.operation !== 'upsert'
    || checkpoint.sequence !== page.next_cursor
  ) {
    throw new SnapshotContractError('The snapshot checkpoint identity was invalid.');
  }
  const expectedPath = `/api/v1/mobile/sync/snapshot?trip_id=${tripId}`;
  const payload = z
    .object({ resource_path: z.literal(expectedPath) })
    .strict()
    .safeParse(checkpoint.payload);
  if (!payload.success) {
    throw new SnapshotContractError('The snapshot checkpoint path was invalid.');
  }
  return {
    checkpointCursor: checkpoint.sequence,
    resourcePath: payload.data.resource_path,
  };
}

function sameVersions(
  left: MobileResourceVersions,
  right: MobileResourceVersions,
): boolean {
  return (
    left.manifest === right.manifest
    && left.itinerary === right.itinerary
    && left.common_documents === right.common_documents
    && left.personal_documents === right.personal_documents
    && left.announcements === right.announcements
    && left.rooming === right.rooming
    && left.meals === right.meals
    && left.qr === right.qr
    && left.readiness === right.readiness
    && left.roster === right.roster
  );
}

function sameResourceCounts(
  left: SyncSnapshot['resource_counts'],
  right: SyncSnapshot['resource_counts'],
): boolean {
  return (
    left.announcements === right.announcements
    && left.common_documents === right.common_documents
    && left.personal_documents === right.personal_documents
    && left.roster === right.roster
    && left.attendance_sessions === right.attendance_sessions
  );
}

export function validateSnapshotDescriptor(
  descriptor: SyncSnapshot,
  boundary: SnapshotValidationBoundary,
): void {
  const { checkpointCursor, committedCursor, currentAccessGeneration, role, tripId } = boundary;
  if (
    descriptor.trip.id !== tripId
    || descriptor.trip.role !== role
    || descriptor.trip.access_generation !== descriptor.access_generation
  ) {
    throw new SnapshotContractError('The snapshot identity crossed its active workspace boundary.');
  }
  if (
    descriptor.trip.itinerary_version !== descriptor.versions.itinerary
    || descriptor.trip.common_document_version !== descriptor.versions.common_documents
    || descriptor.trip.announcement_version !== descriptor.versions.announcements
  ) {
    throw new SnapshotContractError('The snapshot repeated inconsistent resource versions.');
  }
  if (descriptor.access_generation < currentAccessGeneration) {
    throw new SnapshotContractError('The snapshot access generation was stale.');
  }
  if (
    descriptor.baseline_cursor < checkpointCursor
    || (
      descriptor.access_generation === currentAccessGeneration
      && descriptor.baseline_cursor < committedCursor
    )
  ) {
    throw new SnapshotContractError('The snapshot baseline would regress synchronized state.');
  }

  const serverTime = Date.parse(descriptor.server_time);
  const expiresAt = descriptor.access_expires_at
    ? Date.parse(descriptor.access_expires_at)
    : null;
  if (
    !Number.isFinite(serverTime)
    || (
      expiresAt !== null
      && (!Number.isFinite(expiresAt) || expiresAt <= serverTime)
    )
  ) {
    throw new SnapshotContractError('The snapshot access lease was expired or invalid.');
  }

  const expected = expectedResourceMap(tripId, role);
  for (const [key, expectedPath] of Object.entries(expected)) {
    if (descriptor.resources[key as keyof typeof descriptor.resources] !== expectedPath) {
      throw new SnapshotContractError('The snapshot exposed an invalid role resource map.');
    }
  }
  const counts = descriptor.resource_counts;
  const passengerCount = role === 'passenger' ? counts.personal_documents : null;
  const rosterCount = role === 'coordinator' || role === 'client_manager'
    ? counts.roster
    : null;
  const attendanceCount = role === 'coordinator' || role === 'client_manager'
    ? counts.attendance_sessions
    : null;
  if (
    counts.personal_documents !== passengerCount
    || counts.roster !== rosterCount
    || counts.attendance_sessions !== attendanceCount
    || (role === 'passenger' && counts.personal_documents === null)
    || (role !== 'passenger' && counts.personal_documents !== null)
    || (
      (role === 'coordinator' || role === 'client_manager')
      && (counts.roster === null || counts.attendance_sessions === null)
    )
    || (
      role === 'passenger'
      && (counts.roster !== null || counts.attendance_sessions !== null)
    )
  ) {
    throw new SnapshotContractError('The snapshot resource counts crossed their role boundary.');
  }
  if (
    (counts.roster ?? 0) > descriptor.max_group_passengers
    || (counts.attendance_sessions ?? 0) > descriptor.max_attendance_sessions_per_group
  ) {
    throw new SnapshotContractError('The snapshot resource count exceeded its advertised capacity.');
  }
  if (
    (descriptor.versions.announcements === 0 && counts.announcements !== 0)
    || (descriptor.versions.common_documents === 0 && counts.common_documents !== 0)
    || (
      descriptor.versions.personal_documents === 0
      && counts.personal_documents !== null
      && counts.personal_documents !== 0
    )
    || (
      descriptor.versions.roster === 0
      && counts.roster !== null
      && counts.roster !== 0
    )
  ) {
    throw new SnapshotContractError('The snapshot resource counts contradicted their versions.');
  }
}

export function assertSameSnapshotFence(
  first: SyncSnapshot,
  second: SyncSnapshot,
): void {
  if (
    first.trip.id !== second.trip.id
    || first.trip.role !== second.trip.role
    || first.access_generation !== second.access_generation
    || !sameVersions(first.versions, second.versions)
    || !sameResourceCounts(first.resource_counts, second.resource_counts)
  ) {
    throw new SnapshotFenceChangedError();
  }
}

export function snapshotVersionsEqual(
  left: MobileResourceVersions,
  right: MobileResourceVersions,
): boolean {
  return sameVersions(left, right);
}
