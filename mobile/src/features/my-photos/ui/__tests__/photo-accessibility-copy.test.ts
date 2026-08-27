import { photoPreviewAccessibilityLabel } from '../photo-accessibility-copy';

test('labels available photos by logical position and empty previews as unavailable', () => {
  expect(photoPreviewAccessibilityLabel(true, 'Photo 2 of 57', 'Preview is being prepared'))
    .toBe('Photo 2 of 57');
  expect(photoPreviewAccessibilityLabel(false, 'Photo 2 of 57', 'Preview is being prepared'))
    .toBe('Preview is being prepared');
});
