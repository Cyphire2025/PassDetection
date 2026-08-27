import type { MyPhotosContext } from '../../data/my-photos-context';
import { PhotoDownloadExecutionRegistry } from '../photo-download-execution-registry';

const context = {
  namespace: 'tenant.account',
  sessionId: 'session',
  agencyId: 'tenant',
  principalId: 'account',
  role: 'passenger',
  tripId: '11111111-1111-4111-8111-111111111111',
  passengerId: '22222222-2222-4222-8222-222222222222',
  signal: new AbortController().signal,
} satisfies MyPhotosContext;

describe('photo transfer settlement fence', () => {
  it('aborts immediately but does not release destructive cleanup until the writer settles', async () => {
    const registry = new PhotoDownloadExecutionRegistry();
    const signal = registry.begin(context, 'job-a', new AbortController().signal);
    let settled = false;
    const wait = registry.abortAndWait(context, 'job-a', new Error('cancelled'))
      .then(() => { settled = true; });

    await Promise.resolve();
    expect(signal.aborted).toBe(true);
    expect(settled).toBe(false);
    registry.finish(context, 'job-a');
    await wait;
    expect(settled).toBe(true);
  });

  it('fails closed instead of permitting cleanup when native settlement times out', async () => {
    jest.useFakeTimers();
    try {
      const registry = new PhotoDownloadExecutionRegistry();
      registry.begin(context, 'job-b', new AbortController().signal);
      const wait = registry.abortAndWait(context, 'job-b', new Error('cancelled'), 1_000);
      jest.advanceTimersByTime(1_000);
      await expect(wait).rejects.toThrow('did not settle');
      registry.finish(context, 'job-b');
    } finally {
      jest.useRealTimers();
    }
  });

  it('fences every native transfer owned by an account namespace before logout', async () => {
    const registry = new PhotoDownloadExecutionRegistry();
    const first = registry.begin(context, 'job-one', new AbortController().signal);
    const second = registry.begin(context, 'job-two', new AbortController().signal);
    let settled = false;
    const wait = registry.abortNamespaceAndWait(
      context.namespace,
      new Error('account lock'),
    ).then(() => { settled = true; });

    await Promise.resolve();
    expect(first.aborted).toBe(true);
    expect(second.aborted).toBe(true);
    expect(settled).toBe(false);
    registry.finish(context, 'job-one');
    await Promise.resolve();
    expect(settled).toBe(false);
    registry.finish(context, 'job-two');
    await wait;
    expect(settled).toBe(true);
  });
});
