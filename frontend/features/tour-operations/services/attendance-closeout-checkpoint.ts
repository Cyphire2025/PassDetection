import {
  operationsApi,
  type AttendanceCloseoutCheckpoint,
} from "@/features/operations/api/operations.api";
import { useAuthStore } from "@/stores/auth.store";

import {
  collectBrowserAttendanceQueueCloseout,
  publishBrowserAttendanceQueueCloseout,
} from "./attendance-scan-queue";
import { getBrowserAttendanceRuntimeHint } from "./browser-offline-authorization";

const MAX_OLDEST_PENDING_AGE_SECONDS = 31_536_000;

type BrowserAuthenticationSnapshot = Readonly<{
  sessionVersion: number;
  userId: string;
}>;

type PublisherRequest = Readonly<{
  authentication: BrowserAuthenticationSnapshot;
  groupId: string;
  sessionId: string;
}>;

type BrowserQueueCloseout = Readonly<{
  oldestQueuedAt: string | null;
  pending: number;
  retryable: number;
  sending: number;
  discardAuditPending: number;
  unreviewedRejected: number;
}>;

type PendingPublisherBatch = {
  promise: Promise<AttendanceCloseoutCheckpoint & { reported_at: string }>;
  reject: (reason?: unknown) => void;
  request: PublisherRequest;
  resolve: (value: AttendanceCloseoutCheckpoint & { reported_at: string }) => void;
};

type PublisherLane = {
  pending: PendingPublisherBatch | null;
};

const publisherLanes = new Map<string, PublisherLane>();

function captureBrowserAuthenticationSnapshot(): BrowserAuthenticationSnapshot {
  const { sessionVersion, user } = useAuthStore.getState();
  if (!user) throw new Error("Coordinator authentication is required.");
  return { sessionVersion, userId: user.id };
}

function assertBrowserAuthenticationSnapshotCurrent(
  snapshot: BrowserAuthenticationSnapshot,
): void {
  const { sessionVersion, user } = useAuthStore.getState();
  if (sessionVersion !== snapshot.sessionVersion || user?.id !== snapshot.userId) {
    throw new Error("The coordinator account changed while closeout evidence was being collected.");
  }
}

async function collectCheckpointForAuthentication(
  authentication: BrowserAuthenticationSnapshot,
  groupId: string,
  sessionId: string,
  now: number,
): Promise<AttendanceCloseoutCheckpoint> {
  assertBrowserAuthenticationSnapshotCurrent(authentication);
  const queue = await collectBrowserAttendanceQueueCloseout({
    authentication,
    groupId,
    sessionId,
  });
  assertBrowserAuthenticationSnapshotCurrent(authentication);
  return checkpointFromQueue(queue, now);
}

function checkpointFromQueue(
  queue: BrowserQueueCloseout,
  now: number,
): AttendanceCloseoutCheckpoint {
  const unresolvedCount = queue.pending + queue.sending + queue.retryable;
  const oldestQueuedAt = queue.oldestQueuedAt === null
    ? null
    : Date.parse(queue.oldestQueuedAt);
  const oldestPendingAge = unresolvedCount > 0
    ? oldestQueuedAt === null || !Number.isFinite(oldestQueuedAt)
      ? MAX_OLDEST_PENDING_AGE_SECONDS
      : Math.min(
          MAX_OLDEST_PENDING_AGE_SECONDS,
          Math.max(0, Math.floor((now - oldestQueuedAt) / 1_000)),
        )
    : null;
  return {
    pending_count: queue.pending,
    sending_count: queue.sending,
    retryable_count: queue.retryable,
    // A discard is not closeout-clean until its privacy-safe server receipt is
    // durable. Reuse the backward-compatible review count while the additive
    // runtime/discard fields roll out on the backend.
    needs_review_count: queue.discardAuditPending,
    unreviewed_rejected_count: queue.unreviewedRejected,
    oldest_pending_age_seconds: oldestPendingAge,
  };
}

export async function collectBrowserAttendanceCloseoutCheckpoint(
  groupId: string,
  sessionId: string,
  now = Date.now(),
): Promise<AttendanceCloseoutCheckpoint> {
  const authentication = captureBrowserAuthenticationSnapshot();
  return collectCheckpointForAuthentication(authentication, groupId, sessionId, now);
}

async function withCrossTabPublisherLock<T>(
  publisherKey: string,
  operation: () => Promise<T>,
): Promise<T> {
  if (typeof navigator === "undefined" || !navigator.locks) return operation();
  return navigator.locks.request(
    `passdetection:attendance-closeout:${publisherKey}`,
    { mode: "exclusive" },
    operation,
  );
}

async function executePublisherRequest(
  publisherKey: string,
  request: PublisherRequest,
) {
  return withCrossTabPublisherLock(publisherKey, async () => {
    assertBrowserAuthenticationSnapshotCurrent(request.authentication);
    return publishBrowserAttendanceQueueCloseout({
      authentication: request.authentication,
      groupId: request.groupId,
      sessionId: request.sessionId,
      publish: async (queue) => {
        assertBrowserAuthenticationSnapshotCurrent(request.authentication);
        const checkpoint = checkpointFromQueue(queue, Date.now());
        const runtimeId = await getBrowserAttendanceRuntimeHint();
        assertBrowserAuthenticationSnapshotCurrent(request.authentication);
        const runtimeAwareCheckpoint = {
          ...checkpoint,
          ...(runtimeId ? { runtime_id: runtimeId } : {}),
        };
        const response = await operationsApi.publishMyAttendanceCloseoutCheckpoint({
          groupId: request.groupId,
          sessionId: request.sessionId,
          checkpoint: runtimeAwareCheckpoint,
        });
        assertBrowserAuthenticationSnapshotCurrent(request.authentication);
        return response;
      },
    });
  });
}

function finishPublisherRun(publisherKey: string, lane: PublisherLane): void {
  const pending = lane.pending;
  if (!pending) {
    if (publisherLanes.get(publisherKey) === lane) publisherLanes.delete(publisherKey);
    return;
  }
  lane.pending = null;
  const next = executePublisherRequest(publisherKey, pending.request);
  next.then(pending.resolve, pending.reject);
  void next.then(
    () => finishPublisherRun(publisherKey, lane),
    () => finishPublisherRun(publisherKey, lane),
  );
}

function enqueuePublisherRequest(
  publisherKey: string,
  request: PublisherRequest,
) {
  const activeLane = publisherLanes.get(publisherKey);
  if (!activeLane) {
    const lane: PublisherLane = { pending: null };
    publisherLanes.set(publisherKey, lane);
    const active = executePublisherRequest(publisherKey, request);
    void active.then(
      () => finishPublisherRun(publisherKey, lane),
      () => finishPublisherRun(publisherKey, lane),
    );
    return active;
  }
  if (activeLane.pending) {
    activeLane.pending.request = request;
    return activeLane.pending.promise;
  }
  let resolve!: (value: AttendanceCloseoutCheckpoint & { reported_at: string }) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<AttendanceCloseoutCheckpoint & { reported_at: string }>(
    (accept, decline) => {
      resolve = accept;
      reject = decline;
    },
  );
  activeLane.pending = { promise, reject, request, resolve };
  return promise;
}

export async function publishBrowserAttendanceCloseoutCheckpoint(
  groupId: string,
  sessionId: string,
) {
  const authentication = captureBrowserAuthenticationSnapshot();
  const publisherKey = `${authentication.userId}:${groupId}:${sessionId}`;
  return enqueuePublisherRequest(publisherKey, {
    authentication,
    groupId,
    sessionId,
  });
}
