import { randomUUID } from 'expo-crypto';

import type { DownloadQuality, MyPhotosAsset } from '../api/contracts';
import type { MyPhotosContext } from '../data/my-photos-context';
import { projectPhotoDownloadSpace } from './download-policy';
import {
  availablePhotoVaultDiskBytes,
  photoVaultStorageUsage,
} from './photo-vault';

const PLAN_TTL_MS = 15 * 60_000;
const SUBSTANTIAL_BYTES = 500 * 1024 * 1024;

export type PlannedPhotoDownloadItem = Readonly<{
  assetId: string;
  qualities: readonly DownloadQuality[];
  originalByteSize: number;
}>;

export type PhotoDownloadPlan = Readonly<{
  id: string;
  kind: 'one' | 'selected' | 'filter_selection' | 'all_matched';
  namespace: string;
  tripId: string;
  passengerId: string;
  galleryRevision: number;
  supportedQualities: readonly DownloadQuality[];
  estimatedBytesByQuality: Readonly<Partial<Record<DownloadQuality, number>>>;
  remainingBytesByQuality: Readonly<Partial<Record<DownloadQuality, number>>>;
  encryptedGrowthBytesByQuality: Readonly<Partial<Record<DownloadQuality, number>>>;
  maximumItemBytesByQuality: Readonly<Partial<Record<DownloadQuality, number>>>;
  requiredDeviceBytesByQuality: Readonly<Partial<Record<DownloadQuality, number>>>;
  canStartByQuality: Readonly<Partial<Record<DownloadQuality, boolean>>>;
  substantialByQuality: Readonly<Partial<Record<DownloadQuality, boolean>>>;
  estimateKindByQuality: Readonly<Partial<Record<DownloadQuality, 'exact' | 'conservative_upper_bound'>>>;
  availableDiskBytes: number;
  substantial: boolean;
  fitsPrivateQuota: boolean;
  itemCount: number;
  createdAt: string;
  expiresAt: string;
  items: readonly PlannedPhotoDownloadItem[];
  filterSelection: Readonly<{
    filter: 'best' | 'possible';
    excludedAssetIds: readonly string[];
  }> | null;
}>;

export function assertPhotoDownloadPlanOwner(
  context: MyPhotosContext,
  plan: PhotoDownloadPlan,
): void {
  if (
    plan.namespace !== context.namespace
    || plan.tripId !== context.tripId
    || plan.passengerId !== context.passengerId
  ) throw new Error('The download plan belongs to another account or trip.');
  if (Date.parse(plan.expiresAt) <= Date.now()) throw new Error('The download plan expired.');
}

export function intersectPhotoDownloadQualities(
  items: readonly PlannedPhotoDownloadItem[],
): DownloadQuality[] {
  const order: readonly DownloadQuality[] = ['original', 'optimized'];
  return order.filter((quality) => items.every((item) => item.qualities.includes(quality)));
}

export function checkedPhotoDownloadSum(values: readonly number[]): number {
  const total = values.reduce((sum, value) => sum + value, 0);
  if (!Number.isSafeInteger(total) || total < 0) throw new Error('Photo size estimate overflowed.');
  return total;
}

export async function buildPhotoDownloadPlan(
  context: MyPhotosContext,
  kind: PhotoDownloadPlan['kind'],
  revision: number,
  itemCount: number,
  items: readonly PlannedPhotoDownloadItem[],
  supportedQualities: readonly DownloadQuality[],
  estimatedBytesByQualityInput: Readonly<Partial<Record<DownloadQuality, number>>>,
  maximumItemBytesByQualityInput: Readonly<Partial<Record<DownloadQuality, number>>>,
  estimateKindByQualityInput: Readonly<Partial<Record<DownloadQuality, 'exact' | 'conservative_upper_bound'>>>,
  retainedByQuality: Readonly<Partial<Record<DownloadQuality, Readonly<{
    completedItemCount: number;
    verifiedPlaintextBytes: number;
  }>>>> = {},
  filterSelection: PhotoDownloadPlan['filterSelection'] = null,
): Promise<PhotoDownloadPlan> {
  if (!Number.isSafeInteger(revision) || revision < 1 || !Number.isSafeInteger(itemCount) || itemCount < 1) {
    throw new Error('The photo download plan is empty or stale.');
  }
  if (!supportedQualities.length) throw new Error('The selected photos do not share a downloadable quality.');
  const availableDiskBytes = availablePhotoVaultDiskBytes();
  const usage = await photoVaultStorageUsage(context.namespace);
  const estimatedBytesByQuality: Partial<Record<DownloadQuality, number>> = {};
  const remainingBytesByQuality: Partial<Record<DownloadQuality, number>> = {};
  const maximumItemBytesByQuality: Partial<Record<DownloadQuality, number>> = {};
  const encryptedGrowthBytesByQuality: Partial<Record<DownloadQuality, number>> = {};
  const requiredDeviceBytesByQuality: Partial<Record<DownloadQuality, number>> = {};
  const canStartByQuality: Partial<Record<DownloadQuality, boolean>> = {};
  const substantialByQuality: Partial<Record<DownloadQuality, boolean>> = {};
  for (const quality of supportedQualities) {
    const total = estimatedBytesByQualityInput[quality];
    const maximumItem = maximumItemBytesByQualityInput[quality];
    if (!Number.isSafeInteger(total) || total === undefined || total < 1) continue;
    if (!Number.isSafeInteger(maximumItem) || maximumItem === undefined || maximumItem < 1) continue;
    const retained = retainedByQuality[quality];
    const projection = projectPhotoDownloadSpace({
      totalPlaintextBytes: total,
      maximumItemBytes: maximumItem,
      itemCount,
      retainedPlaintextBytes: retained?.verifiedPlaintextBytes ?? 0,
      completedItemCount: retained?.completedItemCount ?? 0,
      availableDiskBytes,
      accountVaultBytes: usage.accountBytes,
      appVaultBytes: usage.appBytes,
    });
    const remainingBytes = projection.remainingPlaintextBytes;
    const encryptedGrowth = projection.encryptedGrowthBytes;
    const required = projection.requiredDeviceBytes;
    estimatedBytesByQuality[quality] = total;
    remainingBytesByQuality[quality] = remainingBytes;
    encryptedGrowthBytesByQuality[quality] = encryptedGrowth;
    maximumItemBytesByQuality[quality] = maximumItem;
    requiredDeviceBytesByQuality[quality] = required;
    substantialByQuality[quality] = total >= SUBSTANTIAL_BYTES
      || (availableDiskBytes > 0 && required >= availableDiskBytes * 0.2);
    canStartByQuality[quality] = projection.canStart;
  }
  const usableQualities = supportedQualities.filter(
    (quality) => estimatedBytesByQuality[quality] !== undefined,
  );
  if (!usableQualities.length) throw new Error('The server did not provide a complete storage estimate.');
  const now = Date.now();
  return Object.freeze({
    id: randomUUID(),
    kind,
    namespace: context.namespace,
    tripId: context.tripId,
    passengerId: context.passengerId,
    galleryRevision: revision,
    supportedQualities: Object.freeze(usableQualities),
    estimatedBytesByQuality: Object.freeze(estimatedBytesByQuality),
    remainingBytesByQuality: Object.freeze(remainingBytesByQuality),
    encryptedGrowthBytesByQuality: Object.freeze(encryptedGrowthBytesByQuality),
    maximumItemBytesByQuality: Object.freeze(maximumItemBytesByQuality),
    requiredDeviceBytesByQuality: Object.freeze(requiredDeviceBytesByQuality),
    canStartByQuality: Object.freeze(canStartByQuality),
    substantialByQuality: Object.freeze(substantialByQuality),
    estimateKindByQuality: Object.freeze({ ...estimateKindByQualityInput }),
    availableDiskBytes,
    substantial: usableQualities.some((quality) => substantialByQuality[quality]),
    fitsPrivateQuota: usableQualities.every((quality) => canStartByQuality[quality]),
    itemCount,
    createdAt: new Date(now).toISOString(),
    expiresAt: new Date(now + PLAN_TTL_MS).toISOString(),
    items: Object.freeze([...items]),
    filterSelection,
  });
}

export function plannedPhotoDownloadAsset(asset: MyPhotosAsset): PlannedPhotoDownloadItem {
  return {
    assetId: asset.asset_id,
    qualities: asset.download_qualities,
    originalByteSize: asset.original_byte_size,
  };
}
