export const TEMPORARY_VIEW_CACHE_MAX_FILES = 3;
export const TEMPORARY_VIEW_CACHE_MAX_BYTES = 64 * 1024 * 1024;

export type TemporaryViewCacheEntry = {
  key: string;
  sizeBytes: number;
  lastAccessedAt: number;
};

export function temporaryViewCacheEvictions(
  entries: readonly TemporaryViewCacheEntry[],
  activeKey: string,
): string[] {
  let totalBytes = entries.reduce((total, entry) => total + entry.sizeBytes, 0);
  let totalFiles = entries.length;
  const evictions: string[] = [];
  const candidates = entries
    .filter((entry) => entry.key !== activeKey)
    .toSorted((left, right) => left.lastAccessedAt - right.lastAccessedAt);

  for (const candidate of candidates) {
    if (totalFiles <= TEMPORARY_VIEW_CACHE_MAX_FILES && totalBytes <= TEMPORARY_VIEW_CACHE_MAX_BYTES) break;
    evictions.push(candidate.key);
    totalFiles -= 1;
    totalBytes -= candidate.sizeBytes;
  }
  return evictions;
}
