const MEBIBYTE = 1024 * 1024;

/**
 * Product-owned defaults for encrypted offline artifacts.
 *
 * Keep these limits in one named policy instead of scattering magic numbers through download
 * and cleanup paths. A managed deployment may pass a stricter policy, but it must preserve the
 * invariant that an account limit cannot exceed the whole-app limit.
 */
export const DEFAULT_VAULT_STORAGE_QUOTA_POLICY = Object.freeze({
  maximumAccountBytes: 1024 * MEBIBYTE,
  maximumAppBytes: 3 * 1024 * MEBIBYTE,
  /** Evict to a low-water mark after a hard limit is crossed to avoid one-file thrashing. */
  recoveryTargetRatio: 0.9,
});

export type VaultStorageQuotaPolicy = Readonly<{
  maximumAccountBytes: number;
  maximumAppBytes: number;
  recoveryTargetRatio: number;
}>;

export type VaultRetentionClass = 'required' | 'evictable';

/**
 * A database registration that is eligible to participate in a quota plan.
 *
 * `required` is deliberately the default callers should choose when product intent is unknown.
 * `protectedFromEviction` covers an open viewer, an uncommitted write lease, or another temporary
 * runtime fence. The planner never infers evictability from a filename or file timestamp.
 */
export type VaultQuotaCandidate = Readonly<{
  encryptedUri: string;
  namespace: string;
  encryptedSizeBytes: number;
  retentionClass: VaultRetentionClass;
  downloadedAtMs: number;
  lastOpenedAtMs?: number | null;
  protectedFromEviction?: boolean;
}>;

export type VaultQuotaSnapshot = Readonly<{
  namespace: string;
  accountUsageBytes: number;
  appUsageBytes: number;
  requestedAdditionalBytes: number;
  /** Omit/null when the platform cannot report free disk space reliably. */
  availableDeviceBytes?: number | null;
  /** The operation-specific free-space requirement, including its safety reserve. */
  requiredFreeDeviceBytes?: number | null;
}>;

export type VaultQuotaBlockedScope = 'account' | 'app' | 'device';

export type VaultQuotaPlan = Readonly<{
  status: 'within_quota' | 'eviction_required' | 'blocked';
  evictions: readonly VaultQuotaCandidate[];
  evictionBytes: number;
  blockedScopes: readonly VaultQuotaBlockedScope[];
  projectedAccountBytes: number;
  projectedAppBytes: number;
  projectedAvailableDeviceBytes: number | null;
}>;

function assertNonNegativeSafeInteger(value: number, label: string): void {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error(`${label} must be a non-negative safe integer.`);
  }
}

function validatePolicy(policy: VaultStorageQuotaPolicy): void {
  assertNonNegativeSafeInteger(policy.maximumAccountBytes, 'Account vault quota');
  assertNonNegativeSafeInteger(policy.maximumAppBytes, 'App vault quota');
  if (policy.maximumAccountBytes < 1 || policy.maximumAppBytes < 1) {
    throw new Error('Vault quotas must be greater than zero.');
  }
  if (policy.maximumAccountBytes > policy.maximumAppBytes) {
    throw new Error('The account vault quota cannot exceed the app vault quota.');
  }
  if (
    !Number.isFinite(policy.recoveryTargetRatio)
    || policy.recoveryTargetRatio <= 0
    || policy.recoveryTargetRatio > 1
  ) {
    throw new Error('The vault recovery target ratio must be greater than zero and at most one.');
  }
}

function validateSnapshot(snapshot: VaultQuotaSnapshot): void {
  if (!snapshot.namespace) throw new Error('A vault account namespace is required.');
  assertNonNegativeSafeInteger(snapshot.accountUsageBytes, 'Account vault usage');
  assertNonNegativeSafeInteger(snapshot.appUsageBytes, 'App vault usage');
  assertNonNegativeSafeInteger(snapshot.requestedAdditionalBytes, 'Requested vault growth');
  if (snapshot.accountUsageBytes > snapshot.appUsageBytes) {
    throw new Error('Account vault usage cannot exceed total app vault usage.');
  }

  const available = snapshot.availableDeviceBytes;
  const required = snapshot.requiredFreeDeviceBytes;
  if (available !== undefined && available !== null) {
    assertNonNegativeSafeInteger(available, 'Available device storage');
  }
  if (required !== undefined && required !== null) {
    assertNonNegativeSafeInteger(required, 'Required free device storage');
  }
}

function candidateAccessTime(candidate: VaultQuotaCandidate): number {
  return candidate.lastOpenedAtMs ?? candidate.downloadedAtMs;
}

function validateCandidates(
  snapshot: VaultQuotaSnapshot,
  candidates: readonly VaultQuotaCandidate[],
): void {
  const seenUris = new Set<string>();
  let totalCandidateBytes = 0;
  let accountCandidateBytes = 0;

  for (const candidate of candidates) {
    if (!candidate.encryptedUri || !candidate.namespace) {
      throw new Error('Vault quota candidates require an account namespace and encrypted URI.');
    }
    if (seenUris.has(candidate.encryptedUri)) {
      throw new Error('Vault quota candidates must have unique encrypted URIs.');
    }
    seenUris.add(candidate.encryptedUri);
    assertNonNegativeSafeInteger(candidate.encryptedSizeBytes, 'Encrypted artifact size');
    if (candidate.encryptedSizeBytes < 1) {
      throw new Error('Encrypted artifact size must be greater than zero.');
    }
    if (candidate.retentionClass !== 'required' && candidate.retentionClass !== 'evictable') {
      throw new Error('Vault quota candidate has an invalid retention class.');
    }
    if (!Number.isSafeInteger(candidate.downloadedAtMs) || candidate.downloadedAtMs < 0) {
      throw new Error('Vault quota candidate has an invalid download time.');
    }
    if (
      candidate.lastOpenedAtMs !== undefined
      && candidate.lastOpenedAtMs !== null
      && (!Number.isSafeInteger(candidate.lastOpenedAtMs) || candidate.lastOpenedAtMs < 0)
    ) {
      throw new Error('Vault quota candidate has an invalid last-opened time.');
    }
    totalCandidateBytes += candidate.encryptedSizeBytes;
    if (candidate.namespace === snapshot.namespace) {
      accountCandidateBytes += candidate.encryptedSizeBytes;
    }
    if (!Number.isSafeInteger(totalCandidateBytes) || !Number.isSafeInteger(accountCandidateBytes)) {
      throw new Error('Vault quota candidate bytes exceeded the safe integer range.');
    }
  }

  // Candidate metadata must describe bytes already included in the usage snapshot. Failing
  // closed avoids manufacturing free space from a stale or cross-account registration list.
  if (totalCandidateBytes > snapshot.appUsageBytes) {
    throw new Error('Vault quota candidates exceed measured app vault usage.');
  }
  if (accountCandidateBytes > snapshot.accountUsageBytes) {
    throw new Error('Vault quota candidates exceed measured account vault usage.');
  }
}

/**
 * Creates a deterministic eviction plan without touching SQLite or the filesystem.
 *
 * The caller must supply registrations from the same immutable account/database snapshot used to
 * measure usage. Required and runtime-protected files are never selected. An actual eviction must
 * first detach the selected registration transactionally, then delete its validated managed file;
 * a crash between those steps is repaired by the existing orphan reconciler.
 */
export function planVaultStorageQuota(
  snapshot: VaultQuotaSnapshot,
  candidates: readonly VaultQuotaCandidate[],
  policy: VaultStorageQuotaPolicy = DEFAULT_VAULT_STORAGE_QUOTA_POLICY,
): VaultQuotaPlan {
  validatePolicy(policy);
  validateSnapshot(snapshot);
  validateCandidates(snapshot, candidates);

  const eligible = candidates
    .filter((candidate) => (
      candidate.retentionClass === 'evictable'
      && candidate.protectedFromEviction !== true
    ))
    .slice()
    .sort((left, right) => (
      candidateAccessTime(left) - candidateAccessTime(right)
      || left.downloadedAtMs - right.downloadedAtMs
      || (left.encryptedUri < right.encryptedUri ? -1 : left.encryptedUri > right.encryptedUri ? 1 : 0)
    ));

  let projectedAccountBytes = snapshot.accountUsageBytes + snapshot.requestedAdditionalBytes;
  let projectedAppBytes = snapshot.appUsageBytes + snapshot.requestedAdditionalBytes;
  if (!Number.isSafeInteger(projectedAccountBytes) || !Number.isSafeInteger(projectedAppBytes)) {
    throw new Error('Projected vault usage exceeded the safe integer range.');
  }
  let projectedAvailableDeviceBytes = snapshot.availableDeviceBytes ?? null;
  const selected = new Set<string>();
  const evictions: VaultQuotaCandidate[] = [];

  const select = (candidate: VaultQuotaCandidate): void => {
    if (selected.has(candidate.encryptedUri)) return;
    selected.add(candidate.encryptedUri);
    evictions.push(candidate);
    projectedAppBytes = Math.max(0, projectedAppBytes - candidate.encryptedSizeBytes);
    if (candidate.namespace === snapshot.namespace) {
      projectedAccountBytes = Math.max(0, projectedAccountBytes - candidate.encryptedSizeBytes);
    }
    if (projectedAvailableDeviceBytes !== null) {
      projectedAvailableDeviceBytes += candidate.encryptedSizeBytes;
    }
  };

  if (projectedAccountBytes > policy.maximumAccountBytes) {
    const recoveryTarget = Math.floor(
      policy.maximumAccountBytes * policy.recoveryTargetRatio,
    );
    for (const candidate of eligible) {
      if (projectedAccountBytes <= recoveryTarget) break;
      if (candidate.namespace === snapshot.namespace) select(candidate);
    }
  }

  if (projectedAppBytes > policy.maximumAppBytes) {
    const recoveryTarget = Math.floor(policy.maximumAppBytes * policy.recoveryTargetRatio);
    for (const candidate of eligible) {
      if (projectedAppBytes <= recoveryTarget) break;
      select(candidate);
    }
  }

  const requiredDeviceBytes = snapshot.requiredFreeDeviceBytes ?? null;
  if (
    projectedAvailableDeviceBytes !== null
    && requiredDeviceBytes !== null
    && projectedAvailableDeviceBytes < requiredDeviceBytes
  ) {
    for (const candidate of eligible) {
      if (projectedAvailableDeviceBytes >= requiredDeviceBytes) break;
      select(candidate);
    }
  }

  const blockedScopes: VaultQuotaBlockedScope[] = [];
  if (projectedAccountBytes > policy.maximumAccountBytes) blockedScopes.push('account');
  if (projectedAppBytes > policy.maximumAppBytes) blockedScopes.push('app');
  if (
    projectedAvailableDeviceBytes !== null
    && requiredDeviceBytes !== null
    && projectedAvailableDeviceBytes < requiredDeviceBytes
  ) {
    blockedScopes.push('device');
  }

  return {
    status: blockedScopes.length
      ? 'blocked'
      : evictions.length
        ? 'eviction_required'
        : 'within_quota',
    evictions,
    evictionBytes: evictions.reduce(
      (total, candidate) => total + candidate.encryptedSizeBytes,
      0,
    ),
    blockedScopes,
    projectedAccountBytes,
    projectedAppBytes,
    projectedAvailableDeviceBytes,
  };
}

export class VaultStorageQuotaError extends Error {
  readonly code = 'VAULT_STORAGE_QUOTA_EXCEEDED';
  readonly blockedScopes: readonly VaultQuotaBlockedScope[];

  constructor(blockedScopes: readonly VaultQuotaBlockedScope[]) {
    super(
      blockedScopes.includes('device')
        ? 'There is not enough managed device storage to keep this document offline.'
        : 'The encrypted offline document storage limit has been reached.',
    );
    this.name = 'VaultStorageQuotaError';
    this.blockedScopes = [...blockedScopes];
  }
}
