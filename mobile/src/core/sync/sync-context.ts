import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace, type MobileRole } from '@/core/auth/types';

export type ImmutableSyncContext = Readonly<{
  sessionId: string;
  namespace: string;
  agencyId: string;
  principalId: string;
  role: MobileRole;
  signal: AbortSignal;
}>;

export type SyncContextLease = Readonly<{
  context: ImmutableSyncContext;
  release: () => void;
}>;

export class SyncContextChangedError extends Error {
  readonly code = 'SYNC_CONTEXT_CHANGED';

  constructor() {
    super('The authenticated account changed while synchronization was running.');
    this.name = 'SyncContextChangedError';
  }
}

function matchesActiveSession(context: ImmutableSyncContext): boolean {
  const session = useSessionStore.getState().session;
  return Boolean(
    session &&
    session.sessionId === context.sessionId &&
    session.principal.id === context.principalId &&
    session.principal.agencyId === context.agencyId &&
    session.principal.principalType === context.role &&
    principalAccountNamespace(session.principal) === context.namespace,
  );
}

export function captureSyncContext(): SyncContextLease {
  const session = useSessionStore.getState().session;
  if (!session) throw new Error('Authentication is required.');
  const controller = new AbortController();
  const context: ImmutableSyncContext = Object.freeze({
    sessionId: session.sessionId,
    namespace: principalAccountNamespace(session.principal),
    agencyId: session.principal.agencyId,
    principalId: session.principal.id,
    role: session.principal.principalType,
    signal: controller.signal,
  });
  const unsubscribe = useSessionStore.subscribe(() => {
    if (!matchesActiveSession(context) && !controller.signal.aborted) {
      controller.abort(new SyncContextChangedError());
    }
  });
  return Object.freeze({
    context,
    release: unsubscribe,
  });
}

export function assertSyncContextActive(context: ImmutableSyncContext): void {
  if (context.signal.aborted || !matchesActiveSession(context)) {
    throw new SyncContextChangedError();
  }
}

export function isSyncContextChanged(error: unknown): boolean {
  return error instanceof SyncContextChangedError || (
    error instanceof Error && error.name === 'AbortError'
  );
}
