import { englishMessages } from '@/core/localization/messages';

import { myPhotosGalleryEmptyCopy } from '../gallery-empty-state';

test('distinguishes an empty group gallery from a face-search with no matches', () => {
  expect(myPhotosGalleryEmptyCopy('all', englishMessages)).toEqual({
    title: englishMessages.myPhotosNoGallery(),
    message: englishMessages.myPhotosTripShortcut(),
  });
  expect(myPhotosGalleryEmptyCopy('best', englishMessages)).toEqual({
    title: englishMessages.myPhotosNoMatches(),
    message: englishMessages.myPhotosNoMatchesMessage(),
  });
});
