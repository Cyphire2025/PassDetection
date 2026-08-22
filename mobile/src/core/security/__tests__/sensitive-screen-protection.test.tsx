import { act, render, waitFor } from '@testing-library/react-native';
import * as ScreenCapture from 'expo-screen-capture';
import { AppState, Platform, type AppStateStatus } from 'react-native';

import { SensitiveScreenProtection } from '../sensitive-screen-protection';

jest.mock('expo-screen-capture', () => ({
  allowScreenCaptureAsync: jest.fn(),
  disableAppSwitcherProtectionAsync: jest.fn(),
  enableAppSwitcherProtectionAsync: jest.fn(),
  preventScreenCaptureAsync: jest.fn(),
}));

const mockPreventScreenCapture = jest.mocked(ScreenCapture.preventScreenCaptureAsync);
const mockAllowScreenCapture = jest.mocked(ScreenCapture.allowScreenCaptureAsync);
const mockEnableAppSwitcherProtection = jest.mocked(ScreenCapture.enableAppSwitcherProtectionAsync);
const mockDisableAppSwitcherProtection = jest.mocked(ScreenCapture.disableAppSwitcherProtectionAsync);

beforeEach(() => {
  jest.clearAllMocks();
  mockAllowScreenCapture.mockResolvedValue(undefined);
  mockDisableAppSwitcherProtection.mockResolvedValue(undefined);
  mockEnableAppSwitcherProtection.mockResolvedValue(undefined);
  mockPreventScreenCapture.mockResolvedValue(undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('holds native capture protection only while the sensitive screen is mounted', async () => {
  const first = await render(<SensitiveScreenProtection protectionKey="document-viewer" />);
  const second = await render(<SensitiveScreenProtection protectionKey="document-viewer" />);

  await waitFor(() => expect(mockPreventScreenCapture).toHaveBeenCalledWith('document-viewer'));
  expect(mockPreventScreenCapture).toHaveBeenCalledTimes(1);
  if (Platform.OS === 'ios') {
    expect(mockEnableAppSwitcherProtection).toHaveBeenCalledWith(1);
  }

  await first.unmount();
  expect(mockAllowScreenCapture).not.toHaveBeenCalled();
  await second.unmount();

  await waitFor(() => expect(mockAllowScreenCapture).toHaveBeenCalledWith('document-viewer'));
  if (Platform.OS === 'ios') {
    expect(mockDisableAppSwitcherProtection).toHaveBeenCalledTimes(1);
  }
});

test('uses an opaque fallback while the app is outside the active foreground', async () => {
  let emitAppState: ((state: AppStateStatus) => void) | undefined;
  const removeListener = jest.fn();
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
    emitAppState = listener;
    return { remove: removeListener };
  });

  const screen = await render(<SensitiveScreenProtection protectionKey="manager-preview" />);
  expect(screen.queryByTestId('sensitive-screen-privacy-overlay')).toBeNull();

  await act(async () => {
    emitAppState?.('inactive');
    await Promise.resolve();
  });
  expect(screen.getByTestId('sensitive-screen-privacy-overlay', {
    includeHiddenElements: true,
  })).toBeTruthy();

  await act(async () => {
    emitAppState?.('active');
    await Promise.resolve();
  });
  expect(screen.queryByTestId('sensitive-screen-privacy-overlay')).toBeNull();

  await screen.unmount();
  expect(removeListener).toHaveBeenCalledTimes(1);
});

test('keeps lifecycle privacy available when native capture protection rejects', async () => {
  mockPreventScreenCapture.mockRejectedValueOnce(new Error('native module unavailable'));
  mockEnableAppSwitcherProtection.mockRejectedValueOnce(new Error('native method unavailable'));

  const screen = await render(<SensitiveScreenProtection protectionKey="fallback-preview" />);
  await waitFor(() => expect(mockPreventScreenCapture).toHaveBeenCalledTimes(1));
  expect(screen.queryByTestId('sensitive-screen-privacy-overlay')).toBeNull();
  await expect(screen.unmount()).resolves.toBeUndefined();
});
