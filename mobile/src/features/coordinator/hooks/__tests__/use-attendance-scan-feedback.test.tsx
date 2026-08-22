import { act, renderHook, waitFor } from '@testing-library/react-native';
import { setAudioModeAsync } from 'expo-audio';
import * as Haptics from 'expo-haptics';
import * as SecureStore from 'expo-secure-store';

import { useAttendanceScanFeedback } from '../use-attendance-scan-feedback';

jest.mock('@/core/storage/secure-store-policy', () => ({
  secureValuePolicy: () => ({ options: { keychainService: 'test-scan-feedback' } }),
}));
jest.mock('expo-audio', () => ({
  setAudioModeAsync: jest.fn(async () => undefined),
  useAudioPlayer: jest.fn(() => {
    const React = jest.requireActual<typeof import('react')>('react');
    const playerRef = React.useRef<MockPlayer | null>(null);
    if (!playerRef.current) {
      playerRef.current = mockPlayersForHook[mockPlayerIndex % mockPlayersForHook.length] ?? null;
      mockPlayerIndex += 1;
    }
    return playerRef.current;
  }),
}));
jest.mock('expo-file-system', () => ({
  Paths: { cache: 'file:///cache/' },
  File: class MockFile {
    exists = false;
    uri: string;
    constructor(_base: string, name: string) {
      this.uri = `file:///cache/${name}`;
    }
    create = jest.fn();
    write = jest.fn();
  },
}));
jest.mock('expo-haptics', () => ({
  NotificationFeedbackType: { Error: 'error', Success: 'success', Warning: 'warning' },
  notificationAsync: jest.fn(async () => undefined),
}));
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
}));

type MockPlayer = Readonly<{
  play: jest.Mock;
  replace: jest.Mock;
  seekTo: jest.Mock<Promise<void>, [number]>;
}>;

function player(): MockPlayer {
  return {
    play: jest.fn(),
    replace: jest.fn(),
    seekTo: jest.fn(async (_seconds: number) => undefined),
  };
}

const mockedAudioMode = jest.mocked(setAudioModeAsync);
const mockedHaptics = jest.mocked(Haptics.notificationAsync);
const mockedGetPreference = jest.mocked(SecureStore.getItemAsync);
const mockedSetPreference = jest.mocked(SecureStore.setItemAsync);

let successPlayer: MockPlayer;
let duplicatePlayer: MockPlayer;
let failurePlayer: MockPlayer;
let mockPlayersForHook: MockPlayer[] = [];
let mockPlayerIndex = 0;

beforeEach(() => {
  jest.clearAllMocks();
  successPlayer = player();
  duplicatePlayer = player();
  failurePlayer = player();
  mockPlayersForHook = [successPlayer, duplicatePlayer, failurePlayer];
  mockPlayerIndex = 0;
  mockedGetPreference.mockResolvedValue(null);
  mockedSetPreference.mockResolvedValue(undefined);
});

test('loads audible-by-default feedback, plays the success cue, and persists mute', async () => {
  const { result } = await renderHook(() => useAttendanceScanFeedback());
  await waitFor(() => expect(result.current.preferenceBusy).toBe(false));

  expect(result.current.muted).toBe(false);
  expect(mockedAudioMode).toHaveBeenCalledWith(expect.objectContaining({
    allowsRecording: false,
    shouldPlayInBackground: false,
  }));
  result.current.notify('saved');
  await successPlayer.seekTo.mock.results[0]?.value;
  expect(successPlayer.play).toHaveBeenCalledTimes(1);
  expect(mockedHaptics).toHaveBeenCalledWith('warning');

  await act(async () => {
    await result.current.toggleMuted();
  });
  expect(mockedSetPreference).toHaveBeenCalledWith(
    'global.scan-feedback-audio.v1',
    'muted',
    { keychainService: 'test-scan-feedback' },
  );
  expect(mockedGetPreference).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(result.current.muted).toBe(true));

  result.current.notify('failure');
  expect(mockedHaptics).toHaveBeenLastCalledWith('error');
  expect(failurePlayer.play).not.toHaveBeenCalled();
});

test('restores a persisted mute before allowing any sound', async () => {
  mockedGetPreference.mockResolvedValue('muted');
  const { result } = await renderHook(() => useAttendanceScanFeedback());
  await waitFor(() => expect(result.current.preferenceBusy).toBe(false));

  expect(result.current.muted).toBe(true);
  result.current.notify('duplicate');
  expect(mockedHaptics).toHaveBeenCalledWith('warning');
  expect(duplicatePlayer.play).not.toHaveBeenCalled();
});
