import { nativePathForAppPrivateFileUri } from '../ios-backup';

test('passes one native path to the iOS wrapper without duplicating the file scheme', () => {
  expect(nativePathForAppPrivateFileUri('file:///private/var/mobile/gc-vault-v1')).toBe(
    '/private/var/mobile/gc-vault-v1',
  );
});

test.each([
  '/private/var/mobile/file',
  'content://provider/file',
  'file://relative/file',
  'file:///private/file?query=1',
  'file:///private/file#fragment',
  'file:///private/file\0escape',
])('rejects a non-canonical app-private file URI: %s', (uri) => {
  expect(() => nativePathForAppPrivateFileUri(uri)).toThrow('Invalid app-private file URI.');
});
