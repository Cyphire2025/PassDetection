import * as Sharing from 'expo-sharing';
import { AppState } from 'react-native';

export type PrivatePhotoShareLease = Readonly<{
  uri: string;
  mimeType: 'image/jpeg' | 'image/png' | 'image/webp';
  release: () => void | Promise<void>;
}>;

type SharingBoundary = Readonly<{
  isAvailableAsync: () => Promise<boolean>;
  shareAsync: typeof Sharing.shareAsync;
}>;

/** A decrypted view exists only for the native share-sheet lease. It is
 * released after success, user cancellation, native failure, or app
 * backgrounding; the encrypted vault copy remains untouched. */
export async function sharePrivatePhoto(
  acquire: () => Promise<PrivatePhotoShareLease>,
  dialogTitle: string,
  sharing: SharingBoundary = Sharing,
): Promise<'shared' | 'unavailable'> {
  if (!dialogTitle.trim()) throw new Error('The private photo share title is required.');
  if (!(await sharing.isAvailableAsync())) return 'unavailable';
  const lease = await acquire();
  let released = false;
  const release = async () => {
    if (released) return;
    released = true;
    await lease.release();
  };
  const subscription = AppState.addEventListener('change', (state) => {
    if (state !== 'active') void release().catch(() => undefined);
  });
  try {
    await sharing.shareAsync(lease.uri, {
      dialogTitle,
      mimeType: lease.mimeType,
      UTI: lease.mimeType === 'image/jpeg'
        ? 'public.jpeg'
        : lease.mimeType === 'image/png'
          ? 'public.png'
          : 'org.webmproject.webp',
    });
    return 'shared';
  } finally {
    subscription.remove();
    await release();
  }
}
