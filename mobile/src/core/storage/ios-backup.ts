import { Platform } from 'react-native';
import ReactNativeBlobUtil from 'react-native-blob-util';

const FILE_URI_PREFIX = 'file://';

/**
 * Converts an Expo app-private file URI into the native path expected by
 * react-native-blob-util's iOS wrapper. The wrapper adds the file scheme
 * itself, so forwarding the URI unchanged would produce file://file://...
 */
export function nativePathForAppPrivateFileUri(uri: string): string {
  if (
    !uri.startsWith('file:///')
    || uri.includes('\0')
    || uri.includes('?')
    || uri.includes('#')
  ) {
    throw new Error('Invalid app-private file URI.');
  }
  const path = uri.slice(FILE_URI_PREFIX.length);
  if (!path.startsWith('/')) throw new Error('Invalid app-private file URI.');
  return path;
}

/**
 * Marks one exact app-owned file or dedicated app-owned directory as excluded
 * from iCloud/iTunes backup. Callers remain responsible for constraining the
 * URI to their own managed root before invoking this helper.
 */
export async function excludeAppPrivateUriFromBackup(uri: string): Promise<void> {
  if (Platform.OS !== 'ios') return;
  await ReactNativeBlobUtil.ios.excludeFromBackupKey(nativePathForAppPrivateFileUri(uri));
}
