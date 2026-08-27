import type { CompatibleMessageCatalog } from '@/core/localization/messages';

import type { MyPhotosAsset } from '../api/contracts';

export function myPhotoTileDescription(
  asset: Pick<MyPhotosAsset, 'preparing' | 'tier'>,
  messages: CompatibleMessageCatalog,
): string {
  if (asset.preparing) return messages.myPhotosPreparingPhoto();
  if (asset.tier === 'best') return messages.myPhotosBest();
  if (asset.tier === 'possible') return messages.myPhotosPossible();
  return messages.myPhotosGroupPhoto();
}
