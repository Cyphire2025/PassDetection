import type { PhotoDownloadJob } from '../downloads/download-repository';
import type { PhotoDownloadState } from '../downloads/download-policy';

export type PhotoTileDownloadState = Readonly<{
  downloaded: boolean;
  label: string;
}>;

type Candidate = Readonly<{
  downloaded: boolean;
  label: string;
  rank: number;
  updatedAt: string;
}>;

function displayRank(state: PhotoDownloadState): number {
  switch (state) {
    case 'downloading':
    case 'retrying':
    case 'queued':
    case 'waiting_wifi':
    case 'waiting_media_preparation':
    case 'paused':
      return 4;
    case 'failed':
    case 'corrupt':
    case 'expired_authorization':
      return 3;
    case 'completed':
      return 2;
    case 'cancelled':
      return 1;
    case 'removed':
      return 0;
  }
}

function progressPercent(job: PhotoDownloadJob): number {
  if (!job.expectedSizeBytes || job.expectedSizeBytes <= 0) return 0;
  return Math.min(100, Math.max(0, job.verifiedPlaintextBytes / job.expectedSizeBytes * 100));
}

/** Creates a bounded, display-only projection. It never exposes vault paths,
 * download IDs, account locators, or authorization metadata to grid cells. */
export function photoTileDownloadStates(
  jobs: readonly PhotoDownloadJob[],
  statusLabel: (state: PhotoDownloadState, progressPercent: number) => string,
): ReadonlyMap<string, PhotoTileDownloadState> {
  const values = new Map<string, Candidate>();
  const downloadedAssets = new Set<string>();
  for (const job of jobs) {
    if (job.state === 'removed') continue;
    if (job.state === 'completed') downloadedAssets.add(job.assetId);
    const candidate: Candidate = {
      downloaded: job.state === 'completed',
      label: statusLabel(job.state, progressPercent(job)),
      rank: displayRank(job.state),
      updatedAt: job.updatedAt,
    };
    const current = values.get(job.assetId);
    if (
      !current
      || candidate.rank > current.rank
      || (candidate.rank === current.rank && candidate.updatedAt > current.updatedAt)
    ) {
      values.set(job.assetId, candidate);
    }
  }
  const result = new Map<string, PhotoTileDownloadState>();
  for (const [assetId, candidate] of values) {
    result.set(assetId, {
      downloaded: downloadedAssets.has(assetId) || candidate.downloaded,
      label: candidate.label,
    });
  }
  return result;
}
