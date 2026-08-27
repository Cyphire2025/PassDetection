import { waitFor } from '@testing-library/react-native';
import { AppState, type AppStateStatus, type NativeEventSubscription } from 'react-native';

import { sharePrivatePhoto } from '../share-private-photo';

test.each([
  ['success', async (): Promise<void> => undefined],
  ['cancel or native failure', async (): Promise<void> => { throw new Error('cancelled'); }],
] as const)('releases the decrypted lease after %s', async (_label, shareAsync) => {
  const release = jest.fn(async () => undefined);
  const action = sharePrivatePhoto(
    async () => ({ uri: 'file:///private/cache/photo.jpg', mimeType: 'image/jpeg', release }),
    'Share outside PassDetection',
    { isAvailableAsync: async () => true, shareAsync },
  );

  if (_label === 'success') await expect(action).resolves.toBe('shared');
  else await expect(action).rejects.toThrow('cancelled');
  expect(release).toHaveBeenCalledTimes(1);
});

test('releases the decrypted lease if the app backgrounds while the share sheet is open', async () => {
  const release = jest.fn(async () => undefined);
  const finishShare: { current: (() => void) | null } = { current: null };
  let appStateListener: ((state: AppStateStatus) => void) | null = null;
  const subscription: NativeEventSubscription = { remove: jest.fn() };
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
    appStateListener = listener;
    return subscription;
  });
  const shareAsync = jest.fn(() => new Promise<void>((resolve) => { finishShare.current = resolve; }));
  const action = sharePrivatePhoto(
    async () => ({ uri: 'file:///private/cache/photo.png', mimeType: 'image/png', release }),
    'Share outside PassDetection',
    { isAvailableAsync: async () => true, shareAsync },
  );
  await waitFor(() => expect(appStateListener).not.toBeNull());
  (appStateListener as unknown as (state: AppStateStatus) => void)('background');
  await Promise.resolve();

  expect(release).toHaveBeenCalledTimes(1);
  finishShare.current?.();
  await expect(action).resolves.toBe('shared');
  expect(release).toHaveBeenCalledTimes(1);
  jest.restoreAllMocks();
});

test('does not create a decrypted lease when native sharing is unavailable', async () => {
  const acquire = jest.fn();
  await expect(sharePrivatePhoto(acquire, 'Share outside PassDetection', {
    isAvailableAsync: async () => false,
    shareAsync: async () => undefined,
  })).resolves.toBe('unavailable');
  expect(acquire).not.toHaveBeenCalled();
});
