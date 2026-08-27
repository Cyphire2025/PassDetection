import { englishMessages } from '@/core/localization/messages';

import { myPhotoTileDescription } from '../my-photo-tile-copy';

test.each([
  [{ preparing: false, tier: 'best' }, 'Best Matches'],
  [{ preparing: false, tier: 'possible' }, 'Possible Matches'],
  [{ preparing: false, tier: null }, 'Group photo'],
  [{ preparing: true, tier: null }, 'Preparing photo'],
] as const)('creates an accurate logical tile label for %j', (asset, expected) => {
  expect(myPhotoTileDescription(asset, englishMessages)).toBe(expected);
});
