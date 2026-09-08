import * as SplashScreen from 'expo-splash-screen';

import { hideNativeSplash, prepareNativeSplash } from '../native-splash';

jest.mock('expo-splash-screen', () => ({
  preventAutoHideAsync: jest.fn(async () => true),
  hideAsync: jest.fn(async () => undefined),
}));

const preventAutoHide = jest.mocked(SplashScreen.preventAutoHideAsync);
const hide = jest.mocked(SplashScreen.hideAsync);

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  preventAutoHide.mockResolvedValue(true);
  hide.mockResolvedValue(undefined);
});

afterEach(async () => {
  await hideNativeSplash();
  jest.clearAllTimers();
  jest.useRealTimers();
});

test('releases native splash after a bounded delay without mounting any React component', async () => {
  prepareNativeSplash();
  expect(preventAutoHide).toHaveBeenCalledTimes(1);
  await jest.advanceTimersByTimeAsync(1_499);
  expect(hide).not.toHaveBeenCalled();
  await jest.advanceTimersByTimeAsync(1);
  expect(hide).toHaveBeenCalledTimes(1);
  await jest.advanceTimersByTimeAsync(10_000);
  expect(hide).toHaveBeenCalledTimes(1);
});

test('normal layout handoff cancels the pre-mount watchdog', async () => {
  prepareNativeSplash();
  await jest.advanceTimersByTimeAsync(300);
  await hideNativeSplash();
  expect(hide).toHaveBeenCalledTimes(1);
  await jest.advanceTimersByTimeAsync(10_000);
  expect(hide).toHaveBeenCalledTimes(1);
});

test('rearming startup retains only one watchdog', async () => {
  prepareNativeSplash();
  await jest.advanceTimersByTimeAsync(1_000);
  prepareNativeSplash();
  await jest.advanceTimersByTimeAsync(1_000);
  expect(hide).not.toHaveBeenCalled();
  await jest.advanceTimersByTimeAsync(500);
  expect(hide).toHaveBeenCalledTimes(1);
});

test('native prevent and fallback-hide rejections do not escape as unhandled failures', async () => {
  preventAutoHide.mockRejectedValueOnce(new Error('Already prevented'));
  hide.mockRejectedValueOnce(new Error('Already hidden'));
  prepareNativeSplash();
  await jest.advanceTimersByTimeAsync(1_500);
  expect(hide).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
});

test('a rejected normal handoff still resolves and cancels its fallback timer', async () => {
  prepareNativeSplash();
  hide.mockRejectedValueOnce(new Error('Native handoff rejected'));
  await expect(hideNativeSplash()).resolves.toBeUndefined();
  await jest.advanceTimersByTimeAsync(10_000);
  expect(hide).toHaveBeenCalledTimes(1);
});
