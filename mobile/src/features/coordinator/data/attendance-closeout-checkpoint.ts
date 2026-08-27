import { z } from 'zod';

import { apiRequest } from '@/core/api/client';
import {
  captureAuthenticationSnapshot,
  isAuthenticationSnapshotCurrent,
  type AuthenticationSnapshot,
} from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase } from '@/core/storage/database';

const MAX_OLDEST_PENDING_AGE_SECONDS = 31_536_000;

const AttendanceCloseoutCheckpointShape = {
  pending_count: z.number().int().min(0).max(1_000_000),
  sending_count: z.number().int().min(0).max(1_000_000),
  retryable_count: z.number().int().min(0).max(1_000_000),
  needs_review_count: z.number().int().min(0).max(1_000_000),
  unreviewed_rejected_count: z.number().int().min(0).max(1_000_000),
  oldest_pending_age_seconds: z.number().int().min(0)
    .max(MAX_OLDEST_PENDING_AGE_SECONDS).nullable(),
} as const;

function validateOldestPendingAge(
  value: AttendanceCloseoutCheckpoint,
  context: z.RefinementCtx,
): void {
  const deliveryCount = value.pending_count + value.sending_count + value.retryable_count;
  if (deliveryCount === 0 && value.oldest_pending_age_seconds !== null) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['oldest_pending_age_seconds'],
      message: 'Oldest pending age must be empty for a clear delivery queue.',
    });
  }
  if (deliveryCount > 0 && value.oldest_pending_age_seconds === null) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['oldest_pending_age_seconds'],
      message: 'Oldest pending age is required for unresolved delivery.',
    });
  }
}

export const AttendanceCloseoutCheckpointSchema = z.object(
  AttendanceCloseoutCheckpointShape,
).strict().superRefine(validateOldestPendingAge);

const AttendanceCloseoutCheckpointResponseSchema = z.object({
  ...AttendanceCloseoutCheckpointShape,
  // New servers identify the installation/runtime derived from bearer claims.
  // Older compatible servers may omit it during the rolling window.
  runtime_id: z.string().uuid().nullable().optional(),
  reported_at: z.string().datetime({ offset: true }),
}).strict().superRefine(validateOldestPendingAge);

export type AttendanceCloseoutCheckpoint = z.infer<typeof AttendanceCloseoutCheckpointSchema>;
export type AttendanceCloseoutCheckpointResponse = z.infer<
  typeof AttendanceCloseoutCheckpointResponseSchema
>;

type PublisherRequest = Readonly<{
  account: string;
  authentication: AuthenticationSnapshot;
  sessionId: string;
  tripId: string;
}>;

type PendingPublisherBatch = {
  promise: Promise<AttendanceCloseoutCheckpointResponse>;
  reject: (reason?: unknown) => void;
  request: PublisherRequest;
  resolve: (value: AttendanceCloseoutCheckpointResponse) => void;
};

type PublisherLane = {
  pending: PendingPublisherBatch | null;
};

const publisherLanes = new Map<string, PublisherLane>();

type CloseoutQueueRow = Readonly<{
  count: number;
  oldest_created_at: string | null;
  state: 'pending' | 'sending' | 'retryable' | 'needs_review' | 'rejected';
}>;

function coordinatorNamespace(): string {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principal.principalType !== 'coordinator') {
    throw new Error('Coordinator authentication is required.');
  }
  return principalAccountNamespace(principal);
}

function assertCoordinatorAuthenticationBoundary(
  authentication: AuthenticationSnapshot,
  account: string,
): void {
  const principal = useSessionStore.getState().session?.principal;
  if (
    !isAuthenticationSnapshotCurrent(authentication)
    || !principal
    || principal.principalType !== 'coordinator'
    || principalAccountNamespace(principal) !== account
  ) {
    throw new Error('The coordinator account changed while closeout evidence was being collected.');
  }
}

async function collectCheckpointForAccount(
  account: string,
  tripId: string,
  sessionId: string,
  now: number,
): Promise<AttendanceCloseoutCheckpoint> {
  const database = await openAccountDatabase(account);
  const rows = await database.getAllAsync<CloseoutQueueRow>(
    `SELECT state, COUNT(*) AS count,
            MIN(CASE WHEN state IN ('pending', 'sending', 'retryable')
                     THEN created_at ELSE NULL END) AS oldest_created_at
       FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND (
          state = 'rejected'
          OR (
            state != 'rejected'
            AND CASE WHEN json_valid(payload_json)
              THEN json_extract(payload_json, '$.session_id')
              ELSE NULL
            END = ?
          )
        )
      GROUP BY state`,
    account,
    tripId,
    sessionId,
  );
  const discardAudit = await database.getFirstAsync<Readonly<{ count: number }>>(
    `SELECT COUNT(*) AS count
       FROM attendance_discard_tombstones
      WHERE account_namespace = ? AND trip_id = ? AND session_id = ?
        AND state != 'synchronized'`,
    account,
    tripId,
    sessionId,
  );
  const checkpoint: AttendanceCloseoutCheckpoint = {
    pending_count: 0,
    sending_count: 0,
    retryable_count: 0,
    needs_review_count: 0,
    unreviewed_rejected_count: 0,
    oldest_pending_age_seconds: null,
  };
  let oldestCreatedAt: number | null = null;
  for (const row of rows) {
    if (row.state === 'pending') checkpoint.pending_count = row.count;
    else if (row.state === 'sending') checkpoint.sending_count = row.count;
    else if (row.state === 'retryable') checkpoint.retryable_count = row.count;
    else if (row.state === 'needs_review') checkpoint.needs_review_count = row.count;
    else checkpoint.unreviewed_rejected_count = row.count;
    if (row.oldest_created_at) {
      const createdAt = Date.parse(row.oldest_created_at);
      if (Number.isFinite(createdAt)) {
        oldestCreatedAt = oldestCreatedAt === null
          ? createdAt
          : Math.min(oldestCreatedAt, createdAt);
      }
    }
  }
  if (Number.isSafeInteger(discardAudit?.count) && (discardAudit?.count ?? 0) > 0) {
    checkpoint.needs_review_count += discardAudit!.count;
  }
  const deliveryCount = checkpoint.pending_count
    + checkpoint.sending_count
    + checkpoint.retryable_count;
  if (deliveryCount > 0) {
    checkpoint.oldest_pending_age_seconds = oldestCreatedAt === null
      ? MAX_OLDEST_PENDING_AGE_SECONDS
      : Math.min(
          MAX_OLDEST_PENDING_AGE_SECONDS,
          Math.max(0, Math.floor((now - oldestCreatedAt) / 1_000)),
        );
  }
  return AttendanceCloseoutCheckpointSchema.parse(checkpoint);
}

export async function collectAttendanceCloseoutCheckpoint(
  tripId: string,
  sessionId: string,
  now = Date.now(),
): Promise<AttendanceCloseoutCheckpoint> {
  const authentication = captureAuthenticationSnapshot();
  const account = coordinatorNamespace();
  assertCoordinatorAuthenticationBoundary(authentication, account);
  const checkpoint = await collectCheckpointForAccount(account, tripId, sessionId, now);
  assertCoordinatorAuthenticationBoundary(authentication, account);
  return checkpoint;
}

async function executePublisherRequest(
  request: PublisherRequest,
): Promise<AttendanceCloseoutCheckpointResponse> {
  assertCoordinatorAuthenticationBoundary(request.authentication, request.account);
  const checkpoint = await collectCheckpointForAccount(
    request.account,
    request.tripId,
    request.sessionId,
    Date.now(),
  );
  assertCoordinatorAuthenticationBoundary(request.authentication, request.account);
  const response = await apiRequest(
    `/mobile/coordinator/groups/${request.tripId}/attendance/sessions/${request.sessionId}/closeout-checkpoint`,
    {
      method: 'PUT',
      body: checkpoint,
      schema: AttendanceCloseoutCheckpointResponseSchema,
    },
  );
  assertCoordinatorAuthenticationBoundary(request.authentication, request.account);
  return response;
}

function finishPublisherRun(publisherKey: string, lane: PublisherLane): void {
  const pending = lane.pending;
  if (!pending) {
    if (publisherLanes.get(publisherKey) === lane) publisherLanes.delete(publisherKey);
    return;
  }
  lane.pending = null;
  const next = executePublisherRequest(pending.request);
  next.then(pending.resolve, pending.reject);
  void next.then(
    () => finishPublisherRun(publisherKey, lane),
    () => finishPublisherRun(publisherKey, lane),
  );
}

function enqueuePublisherRequest(
  publisherKey: string,
  request: PublisherRequest,
): Promise<AttendanceCloseoutCheckpointResponse> {
  const activeLane = publisherLanes.get(publisherKey);
  if (!activeLane) {
    const lane: PublisherLane = { pending: null };
    publisherLanes.set(publisherKey, lane);
    const active = executePublisherRequest(request);
    void active.then(
      () => finishPublisherRun(publisherKey, lane),
      () => finishPublisherRun(publisherKey, lane),
    );
    return active;
  }
  if (activeLane.pending) {
    // Coalesce repeated interval/manual/remount triggers, but retain the newest
    // authentication context and recompute after the active request settles.
    activeLane.pending.request = request;
    return activeLane.pending.promise;
  }
  let resolve!: (value: AttendanceCloseoutCheckpointResponse) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<AttendanceCloseoutCheckpointResponse>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  activeLane.pending = { promise, reject, request, resolve };
  return promise;
}

export async function publishAttendanceCloseoutCheckpoint(
  tripId: string,
  sessionId: string,
): Promise<AttendanceCloseoutCheckpointResponse> {
  const authentication = captureAuthenticationSnapshot();
  const account = coordinatorNamespace();
  assertCoordinatorAuthenticationBoundary(authentication, account);
  const publisherKey = `${account}:${tripId}:${sessionId}`;
  return enqueuePublisherRequest(publisherKey, {
    account,
    authentication,
    sessionId,
    tripId,
  });
}
