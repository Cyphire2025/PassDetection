import {
  DEFAULT_VAULT_STORAGE_QUOTA_POLICY,
  VaultStorageQuotaError,
  planVaultStorageQuota,
  type VaultQuotaCandidate,
  type VaultStorageQuotaPolicy,
} from '../vault-quota-policy';

const policy: VaultStorageQuotaPolicy = {
  maximumAccountBytes: 100,
  maximumAppBytes: 200,
  recoveryTargetRatio: 0.8,
};

function candidate(
  encryptedUri: string,
  overrides: Partial<VaultQuotaCandidate> = {},
): VaultQuotaCandidate {
  return {
    encryptedUri,
    namespace: 'account-a',
    encryptedSizeBytes: 20,
    retentionClass: 'evictable',
    downloadedAtMs: 100,
    lastOpenedAtMs: null,
    ...overrides,
  };
}

describe('encrypted vault quota policy', () => {
  test('publishes explicit account/app defaults with a low-water recovery target', () => {
    expect(DEFAULT_VAULT_STORAGE_QUOTA_POLICY).toEqual({
      maximumAccountBytes: 1024 * 1024 * 1024,
      maximumAppBytes: 3 * 1024 * 1024 * 1024,
      recoveryTargetRatio: 0.9,
    });
  });

  test('does not evict while the projected write remains inside both hard limits', () => {
    const plan = planVaultStorageQuota({
      namespace: 'account-a',
      accountUsageBytes: 50,
      appUsageBytes: 120,
      requestedAdditionalBytes: 10,
    }, [candidate('file:///a.gcv')], policy);

    expect(plan).toEqual({
      status: 'within_quota',
      evictions: [],
      evictionBytes: 0,
      blockedScopes: [],
      projectedAccountBytes: 60,
      projectedAppBytes: 130,
      projectedAvailableDeviceBytes: null,
    });
  });

  test('evicts least-recently-opened account artifacts to the low-water mark', () => {
    const pinnedOldest = candidate('file:///pinned.gcv', {
      encryptedSizeBytes: 30,
      retentionClass: 'required',
      lastOpenedAtMs: 1,
    });
    const otherAccount = candidate('file:///other.gcv', {
      namespace: 'account-b',
      encryptedSizeBytes: 40,
      lastOpenedAtMs: 0,
    });
    const oldestEvictable = candidate('file:///oldest.gcv', { lastOpenedAtMs: 10 });
    const newerEvictable = candidate('file:///newer.gcv', { lastOpenedAtMs: 20 });
    const input = [pinnedOldest, otherAccount, newerEvictable, oldestEvictable];

    const plan = planVaultStorageQuota({
      namespace: 'account-a',
      accountUsageBytes: 90,
      appUsageBytes: 180,
      requestedAdditionalBytes: 15,
    }, input, policy);

    expect(plan.status).toBe('eviction_required');
    expect(plan.evictions.map((item) => item.encryptedUri)).toEqual([
      'file:///oldest.gcv',
      'file:///newer.gcv',
    ]);
    expect(plan.evictions).not.toContain(pinnedOldest);
    expect(plan.evictions).not.toContain(otherAccount);
    expect(plan.projectedAccountBytes).toBe(65);
    expect(plan.projectedAppBytes).toBe(155);
    expect(input.map((item) => item.encryptedUri)).toEqual([
      'file:///pinned.gcv',
      'file:///other.gcv',
      'file:///newer.gcv',
      'file:///oldest.gcv',
    ]);
  });

  test('uses app-wide LRU candidates when only the whole-app quota is crossed', () => {
    const appPolicy = { ...policy, maximumAppBytes: 100, recoveryTargetRatio: 0.9 };
    const plan = planVaultStorageQuota({
      namespace: 'account-a',
      accountUsageBytes: 40,
      appUsageBytes: 95,
      requestedAdditionalBytes: 10,
    }, [
      candidate('file:///current.gcv', { lastOpenedAtMs: 50 }),
      candidate('file:///other.gcv', {
        namespace: 'account-b',
        lastOpenedAtMs: 5,
      }),
    ], appPolicy);

    expect(plan.status).toBe('eviction_required');
    expect(plan.evictions.map((item) => item.encryptedUri)).toEqual(['file:///other.gcv']);
    expect(plan.projectedAccountBytes).toBe(50);
    expect(plan.projectedAppBytes).toBe(85);
  });

  test('recovers low disk space without selecting pinned or runtime-protected files', () => {
    const plan = planVaultStorageQuota({
      namespace: 'account-a',
      accountUsageBytes: 90,
      appUsageBytes: 120,
      requestedAdditionalBytes: 0,
      availableDeviceBytes: 10,
      requiredFreeDeviceBytes: 35,
    }, [
      candidate('file:///required.gcv', {
        encryptedSizeBytes: 30,
        retentionClass: 'required',
        lastOpenedAtMs: 1,
      }),
      candidate('file:///open-viewer.gcv', {
        encryptedSizeBytes: 30,
        protectedFromEviction: true,
        lastOpenedAtMs: 2,
      }),
      candidate('file:///old.gcv', {
        encryptedSizeBytes: 15,
        lastOpenedAtMs: 3,
      }),
      candidate('file:///new.gcv', {
        encryptedSizeBytes: 10,
        lastOpenedAtMs: 4,
      }),
    ], policy);

    expect(plan.status).toBe('eviction_required');
    expect(plan.evictions.map((item) => item.encryptedUri)).toEqual([
      'file:///old.gcv',
      'file:///new.gcv',
    ]);
    expect(plan.projectedAvailableDeviceBytes).toBe(35);
  });

  test('reports a blocked low-disk state instead of silently removing required data', () => {
    const plan = planVaultStorageQuota({
      namespace: 'account-a',
      accountUsageBytes: 50,
      appUsageBytes: 50,
      requestedAdditionalBytes: 0,
      availableDeviceBytes: 5,
      requiredFreeDeviceBytes: 20,
    }, [candidate('file:///required.gcv', {
      encryptedSizeBytes: 50,
      retentionClass: 'required',
      lastOpenedAtMs: 0,
    })], policy);

    expect(plan.status).toBe('blocked');
    expect(plan.evictions).toEqual([]);
    expect(plan.blockedScopes).toEqual(['device']);
    expect(new VaultStorageQuotaError(plan.blockedScopes)).toMatchObject({
      code: 'VAULT_STORAGE_QUOTA_EXCEEDED',
      blockedScopes: ['device'],
    });
  });

  test('blocks a write that cannot fit without eligible artifacts', () => {
    const plan = planVaultStorageQuota({
      namespace: 'account-a',
      accountUsageBytes: 90,
      appUsageBytes: 190,
      requestedAdditionalBytes: 20,
    }, [candidate('file:///required.gcv', {
      encryptedSizeBytes: 90,
      retentionClass: 'required',
    })], policy);

    expect(plan.status).toBe('blocked');
    expect(plan.blockedScopes).toEqual(['account', 'app']);
    expect(plan.projectedAccountBytes).toBe(110);
    expect(plan.projectedAppBytes).toBe(210);
  });

  test('fails closed on duplicate or physically impossible registration snapshots', () => {
    const snapshot = {
      namespace: 'account-a',
      accountUsageBytes: 20,
      appUsageBytes: 20,
      requestedAdditionalBytes: 1,
    };
    const duplicate = candidate('file:///same.gcv', { encryptedSizeBytes: 10 });

    expect(() => planVaultStorageQuota(snapshot, [duplicate, duplicate], policy)).toThrow(
      'unique encrypted URIs',
    );
    expect(() => planVaultStorageQuota({ ...snapshot, appUsageBytes: 30 }, [candidate('file:///too-large.gcv', {
      encryptedSizeBytes: 21,
    })], policy)).toThrow('exceed measured account vault usage');
  });
});
