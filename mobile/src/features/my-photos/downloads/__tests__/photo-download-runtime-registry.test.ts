import {
  PhotoDownloadRuntimeLockedError,
  PhotoDownloadRuntimeRegistry,
} from '../photo-download-runtime-registry';

type FileSystem = Readonly<{ readFileSync: (path: string, encoding: 'utf8') => string }>;
type PathModule = Readonly<{ join: (...parts: string[]) => string }>;
const fileSystem = jest.requireActual<FileSystem>('fs');
const pathModule = jest.requireActual<PathModule>('path');
const processModule = jest.requireActual<{ cwd: () => string }>('process');

describe('My Photos whole-runtime account fence', () => {
  it('aborts and settles a drain before logout and prevents its requested second claim', async () => {
    const namespace = 'tenant.account';
    const sessionId = 'session-one';
    const tripId = 'trip-one';
    const registry = new PhotoDownloadRuntimeRegistry();
    registry.activateNamespace(namespace, sessionId);
    const lease = registry.begin(namespace, sessionId, tripId, new AbortController().signal);
    let claims = 0;
    let writes = 0;
    let releaseFirstJob!: () => void;
    const firstJob = new Promise<void>((resolve) => { releaseFirstJob = resolve; });
    let resolveFirstClaimed!: () => void;
    const firstClaimed = new Promise<void>((resolve) => { resolveFirstClaimed = resolve; });

    const drain = (async () => {
      try {
        while (claims < 2) {
          if (lease.signal.aborted) throw lease.signal.reason;
          claims += 1;
          writes += 1;
          if (claims === 1) {
            resolveFirstClaimed();
            await firstJob;
          }
        }
      } finally {
        lease.finish();
      }
    })();

    await firstClaimed;
    const settlement = registry.abortNamespaceAndWait(namespace, new Error('account lock'));
    expect(lease.signal.aborted).toBe(true);
    expect(() => registry.activateNamespace(namespace, sessionId))
      .toThrow(PhotoDownloadRuntimeLockedError);
    expect(() => registry.begin(namespace, sessionId, tripId, new AbortController().signal))
      .toThrow(PhotoDownloadRuntimeLockedError);

    releaseFirstJob();
    await expect(drain).rejects.toThrow('account lock');
    await expect(settlement).resolves.toBeUndefined();
    expect({ claims, writes }).toEqual({ claims: 1, writes: 1 });
    expect(() => registry.begin(namespace, sessionId, tripId, new AbortController().signal))
      .toThrow(PhotoDownloadRuntimeLockedError);
  });

  it('temporarily fences the whole namespace, settles cross-trip work, and safely reopens the same session', async () => {
    const namespace = 'tenant.account';
    const sessionId = 'session-one';
    const tripId = 'trip-one';
    const registry = new PhotoDownloadRuntimeRegistry();
    registry.activateNamespace(namespace, sessionId);
    const producer = registry.begin(namespace, sessionId, tripId, new AbortController().signal);
    const otherTripView = registry.begin(
      namespace,
      sessionId,
      'trip-two',
      new AbortController().signal,
    );
    let destructiveOperationEntered = false;

    const clearing = registry.runExclusiveNamespace(
      namespace,
      sessionId,
      tripId,
      new AbortController().signal,
      new Error('clear storage'),
      async (signal) => {
        destructiveOperationEntered = true;
        expect(signal.aborted).toBe(false);
        expect(() => registry.begin(
          namespace,
          sessionId,
          tripId,
          new AbortController().signal,
        )).toThrow(PhotoDownloadRuntimeLockedError);
        return 7;
      },
    );

    expect(producer.signal.aborted).toBe(true);
    expect(otherTripView.signal.aborted).toBe(true);
    expect(destructiveOperationEntered).toBe(false);
    expect(() => registry.begin(
      namespace,
      sessionId,
      tripId,
      new AbortController().signal,
    )).toThrow(PhotoDownloadRuntimeLockedError);
    expect(() => registry.begin(
      namespace,
      sessionId,
      'trip-two',
      new AbortController().signal,
    )).toThrow(PhotoDownloadRuntimeLockedError);

    producer.finish();
    expect(destructiveOperationEntered).toBe(false);
    otherTripView.finish();
    await expect(clearing).resolves.toBe(7);
    expect(destructiveOperationEntered).toBe(true);
    const resumed = registry.begin(
      namespace,
      sessionId,
      tripId,
      new AbortController().signal,
    );
    expect(resumed.signal.aborted).toBe(false);
    resumed.finish();
  });

  it('keeps a timed-out clear fence closed until its cancelled predecessor settles', async () => {
    jest.useFakeTimers();
    try {
      const namespace = 'tenant.account';
      const sessionId = 'session-one';
      const tripId = 'trip-one';
      const registry = new PhotoDownloadRuntimeRegistry();
      registry.activateNamespace(namespace, sessionId);
      const producer = registry.begin(namespace, sessionId, tripId, new AbortController().signal);
      const clearing = registry.runExclusiveNamespace(
        namespace,
        sessionId,
        tripId,
        new AbortController().signal,
        new Error('clear storage'),
        async () => undefined,
        1_000,
      );
      const rejection = expect(clearing).rejects.toThrow('did not settle before storage clearing');

      jest.advanceTimersByTime(1_000);
      await rejection;
      expect(() => registry.begin(
        namespace,
        sessionId,
        tripId,
        new AbortController().signal,
      )).toThrow(PhotoDownloadRuntimeLockedError);

      producer.finish();
      for (let index = 0; index < 4; index += 1) await Promise.resolve();
      const resumed = registry.begin(
        namespace,
        sessionId,
        tripId,
        new AbortController().signal,
      );
      expect(resumed.signal.aborted).toBe(false);
      resumed.finish();
    } finally {
      jest.useRealTimers();
    }
  });

  it('allows the same account to resume only after a later authenticated activation', async () => {
    const namespace = 'tenant.account';
    const registry = new PhotoDownloadRuntimeRegistry();
    await registry.abortNamespaceAndWait(namespace, new Error('account lock'));
    expect(() => registry.begin(namespace, 'old-session', 'trip-one', new AbortController().signal))
      .toThrow(PhotoDownloadRuntimeLockedError);

    registry.activateNamespace(namespace, 'new-session');
    const next = registry.begin(namespace, 'new-session', 'trip-one', new AbortController().signal);
    expect(next.signal.aborted).toBe(false);
    next.finish();
  });

  it('fails closed if a whole runtime does not settle before the lock deadline', async () => {
    jest.useFakeTimers();
    try {
      const namespace = 'tenant.account';
      const registry = new PhotoDownloadRuntimeRegistry();
      registry.activateNamespace(namespace, 'session-one');
      const lease = registry.begin(namespace, 'session-one', 'trip-one', new AbortController().signal);
      const settlement = registry.abortNamespaceAndWait(namespace, new Error('account lock'), 1_000);
      jest.advanceTimersByTime(1_000);
      await expect(settlement).rejects.toThrow('did not settle');
      expect(() => registry.activateNamespace(namespace, 'session-two')).toThrow('earlier account run');
      lease.finish();
    } finally {
      jest.useRealTimers();
    }
  });

  it('keeps every download hook query and mutation behind the namespace fence', () => {
    const hooks = fileSystem.readFileSync(pathModule.join(
      processModule.cwd(),
      'src/features/my-photos/hooks/use-photo-downloads.ts',
    ), 'utf8');
    const directContextBoundaries = hooks.match(/\bwithMyPhotosContext\(/g) ?? [];
    const fencedBoundaries = hooks.match(/\bwithFencedPhotoDownloadContext\(/g) ?? [];
    const retainedBoundaries = hooks.match(/\bbeginPhotoDownloadNamespaceOperation\(/g) ?? [];
    const exclusiveBoundaries = hooks.match(/\bwithExclusivePhotoDownloadNamespaceOperation\(/g) ?? [];
    expect(directContextBoundaries).toHaveLength(2);
    expect(fencedBoundaries.length).toBeGreaterThanOrEqual(9);
    expect(retainedBoundaries).toHaveLength(1);
    expect(exclusiveBoundaries).toHaveLength(1);
  });
});
