export type GallerySelection =
  | Readonly<{ mode: 'explicit'; assetIds: ReadonlySet<string> }>
  | Readonly<{ mode: 'all_filter'; excludedAssetIds: ReadonlySet<string>; totalCount: number }>;

export const emptyGallerySelection: GallerySelection = Object.freeze({
  mode: 'explicit',
  assetIds: new Set<string>(),
});

export function gallerySelectionCount(selection: GallerySelection): number {
  return selection.mode === 'explicit'
    ? selection.assetIds.size
    : Math.max(0, selection.totalCount - selection.excludedAssetIds.size);
}

export function galleryAssetSelected(selection: GallerySelection, assetId: string): boolean {
  return selection.mode === 'explicit'
    ? selection.assetIds.has(assetId)
    : !selection.excludedAssetIds.has(assetId);
}

export function toggleGalleryAsset(
  selection: GallerySelection,
  assetId: string,
): GallerySelection {
  if (selection.mode === 'explicit') {
    const assetIds = new Set(selection.assetIds);
    if (assetIds.has(assetId)) assetIds.delete(assetId);
    else assetIds.add(assetId);
    return { mode: 'explicit', assetIds };
  }
  const excludedAssetIds = new Set(selection.excludedAssetIds);
  if (excludedAssetIds.has(assetId)) excludedAssetIds.delete(assetId);
  else excludedAssetIds.add(assetId);
  return { ...selection, excludedAssetIds };
}

export function selectEveryFilterResult(totalCount: number): GallerySelection {
  if (!Number.isSafeInteger(totalCount) || totalCount < 0) {
    throw new Error('Gallery selection count is invalid.');
  }
  return { mode: 'all_filter', excludedAssetIds: new Set(), totalCount };
}

export function canSelectEveryFilterResult(filter: 'best' | 'possible' | 'all'): boolean {
  return filter === 'best' || filter === 'possible';
}
