import type { CompatibleMessageCatalog } from '@/core/localization/messages';

import type { MatchFilter } from '../api/contracts';

export function myPhotosGalleryEmptyCopy(
  filter: MatchFilter,
  messages: CompatibleMessageCatalog,
): Readonly<{ title: string; message: string }> {
  return filter === 'all'
    ? {
        title: messages.myPhotosNoGallery(),
        message: messages.myPhotosTripShortcut(),
      }
    : {
        title: messages.myPhotosNoMatches(),
        message: messages.myPhotosNoMatchesMessage(),
      };
}
