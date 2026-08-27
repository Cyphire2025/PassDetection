import type { MyPhotosAsset } from '../api/contracts';

export function canSubmitMyPhotoFeedback(
  asset: Pick<MyPhotosAsset, 'match_id' | 'tier'>,
): boolean {
  return asset.match_id !== null && asset.tier !== null;
}
