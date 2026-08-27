import { act, renderHook, waitFor } from '@testing-library/react-native';
import { AppState, type AppStateStatus } from 'react-native';

import type { LocalPhotoLease } from '../../downloads/download-manager';
import { usePrivatePhotoView } from '../use-private-photo-view';

const ORIGINAL_APP_STATE = Object.getOwnPropertyDescriptor(AppState, 'currentState');

afterEach(() => {
  jest.restoreAllMocks();
  if (ORIGINAL_APP_STATE) Object.defineProperty(AppState, 'currentState', ORIGINAL_APP_STATE);
});

test('releases decrypted views on background, asset change, and unmount', async () => {
  let stateListener: ((state: AppStateStatus) => void) | null = null;
  const removeListener = jest.fn();
  const addListener = jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
    stateListener = listener;
    return { remove: removeListener };
  });
  Object.defineProperty(AppState, 'currentState', {
    configurable: true,
    value: 'active',
    writable: true,
  });
  const releases = [jest.fn(), jest.fn(), jest.fn()];
  let leaseIndex = 0;
  const openLocal = jest.fn(async (assetId: string): Promise<LocalPhotoLease> => {
    const index = leaseIndex++;
    return {
      uri: `file:///private-view-${index}.jpg`,
      mimeType: 'image/jpeg',
      quality: 'original',
      jobId: `job-${assetId}-${index}`,
      release: releases[index]!,
    };
  });

  const hook = await renderHook(
    ({ assetId }: Readonly<{ assetId: string }>) => usePrivatePhotoView(assetId, openLocal),
    { initialProps: { assetId: 'asset-a' } },
  );
  await waitFor(() => expect(hook.result.current?.assetId).toBe('asset-a'));

  await act(() => stateListener?.('background'));
  await waitFor(() => expect(hook.result.current).toBeNull());
  expect(releases[0]).toHaveBeenCalledTimes(1);

  await act(() => stateListener?.('active'));
  await waitFor(() => expect(hook.result.current?.assetId).toBe('asset-a'));
  expect(openLocal).toHaveBeenCalledTimes(2);

  await hook.rerender({ assetId: 'asset-b' });
  await waitFor(() => expect(hook.result.current?.assetId).toBe('asset-b'));
  expect(releases[1]).toHaveBeenCalledTimes(1);

  await hook.unmount();
  expect(releases[2]).toHaveBeenCalledTimes(1);
  expect(removeListener).toHaveBeenCalledTimes(1);

  addListener.mockRestore();
});
