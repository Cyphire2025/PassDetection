import {
  assertSyncContextActive,
  captureSyncContext,
  type ImmutableSyncContext,
} from '@/core/sync/sync-context';

export async function withAccountQueryContext<T>(
  querySignal: AbortSignal,
  operation: (context: ImmutableSyncContext) => Promise<T>,
): Promise<T> {
  const lease = captureSyncContext();
  const context: ImmutableSyncContext = Object.freeze({
    ...lease.context,
    signal: AbortSignal.any([lease.context.signal, querySignal]),
  });
  try {
    assertSyncContextActive(context);
    const result = await operation(context);
    assertSyncContextActive(context);
    return result;
  } finally {
    lease.release();
  }
}
