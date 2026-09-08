/* eslint-disable @typescript-eslint/no-require-imports -- Native video host is mocked after Jest hoisting. */
import { act, fireEvent, render } from '@testing-library/react-native';
import { useContext, useEffect } from 'react';
import { AccessibilityInfo, Animated, AppState, Pressable, StyleSheet, Text, type AppStateStatus } from 'react-native';

import { AppLaunchGate } from '../app-launch-gate';
import { LaunchChoreographyContext, LaunchEntrance, LaunchLogoAnchor } from '../launch-choreography';
import { launchDockGeometry, type LaunchRect } from '../launch-geometry';

type PlayerEvent = { status?: string };
const mockPlayerListeners = new Map<string, Set<(event: PlayerEvent) => void>>();
const mockLifecycleListeners = new Set<(state: AppStateStatus) => void>();
const mockPreferenceListeners = new Set<(enabled: boolean) => void>();
const mockHideAsync = jest.fn(async () => undefined);
const mockMarkInteractive = jest.fn();
const mockCreatePlayer = jest.fn();
const mockTransitions: Animated.CompositeAnimation[] = [];
let mockConstructionFails = false;
let mockIsDevice = false;
const mockPlayer = {
  status: 'readyToPlay',
  loop: true,
  muted: false,
  volume: 1,
  audioMixingMode: 'auto',
  allowsExternalPlayback: true,
  showNowPlayingNotification: true,
  staysActiveInBackground: true,
  play: jest.fn(),
  pause: jest.fn(),
  addListener: jest.fn((event: string, callback: (value: PlayerEvent) => void) => {
    const callbacks = mockPlayerListeners.get(event) ?? new Set();
    callbacks.add(callback);
    mockPlayerListeners.set(event, callbacks);
    return { remove: jest.fn(() => { callbacks.delete(callback); }) };
  }),
};

jest.mock('expo-splash-screen', () => ({ hideAsync: () => mockHideAsync() }));
jest.mock('expo-status-bar', () => ({ StatusBar: () => null }));
jest.mock('expo-device', () => ({ get isDevice() { return mockIsDevice; } }));
jest.mock('../../../../assets/videos/global-connect-launch-4k.mp4', () => 401);
jest.mock('../../../../assets/videos/global-connect-launch-compatible.mp4', () => 402);
jest.mock('@/core/observability/mobile-observability', () => ({
  markApplicationInteractive: () => mockMarkInteractive(),
}));
jest.mock('expo-video', () => {
  const React = require('react') as typeof import('react');
  const { View: MockView } = require('react-native') as typeof import('react-native');
  return {
    useVideoPlayer: (source: number, setup: (player: typeof mockPlayer) => void) => React.useState(() => {
      if (mockConstructionFails) throw new Error('Native decoder unavailable');
      mockCreatePlayer(source);
      setup(mockPlayer);
      return mockPlayer;
    })[0],
    VideoView: (props: Record<string, unknown>) => React.createElement(MockView, props),
  };
});

const hidden = { includeHiddenElements: true };
const originalAppState = AppState.currentState;

async function emitPlayer(event: string, value: PlayerEvent = {}) {
  await act(async () => {
    for (const callback of mockPlayerListeners.get(event) ?? []) callback(value);
  });
}

async function advance(milliseconds: number) {
  await act(async () => { jest.advanceTimersByTime(milliseconds); });
}

async function openLaunch(appReady = true) {
  const screen = await render(
    <AppLaunchGate appReady={appReady}><Text>Application destination</Text></AppLaunchGate>,
  );
  await fireEvent(screen.getByTestId('app-launch-screen'), 'layout', {
    nativeEvent: { layout: { x: 0, y: 0, width: 390, height: 844 } },
  });
  return screen;
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  mockHideAsync.mockResolvedValue(undefined);
  mockPlayer.play.mockReset();
  mockPlayer.pause.mockReset();
  mockPlayer.status = 'readyToPlay';
  mockConstructionFails = false;
  mockIsDevice = false;
  mockPlayerListeners.clear();
  mockLifecycleListeners.clear();
  mockPreferenceListeners.clear();
  mockTransitions.length = 0;
  // The RN native-animation Jest mock finishes in16ms irrespective of duration.
  // Keep its actual Value/interpolation, but model the native completion clock.
  jest.spyOn(Animated, 'timing').mockImplementation((value, configuration) => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let callback: ((result: { finished: boolean }) => void) | undefined;
    const animation = {
      start: jest.fn((onEnd?: (result: { finished: boolean }) => void) => {
        callback = onEnd;
        timer = setTimeout(() => {
          (value as Animated.Value).setValue(configuration.toValue as number);
          const complete = callback;
          callback = undefined;
          complete?.({ finished: true });
        }, (configuration.delay ?? 0) + (configuration.duration ?? 500));
      }),
      stop: jest.fn(() => {
        clearTimeout(timer);
        const interrupted = callback;
        callback = undefined;
        interrupted?.({ finished: false });
      }),
      reset: jest.fn(() => { clearTimeout(timer); }),
    };
    mockTransitions.push(animation);
    return animation;
  });
  jest.spyOn(require('react-native') as typeof import('react-native'), 'useWindowDimensions').mockReturnValue({
    width: 390, height: 844, scale: 3, fontScale: 1,
  });
  (AppState as unknown as { currentState: string }).currentState = 'active';
  jest.spyOn(AccessibilityInfo, 'isReduceMotionEnabled').mockResolvedValue(false);
  // This suite exercises only reduceMotionChanged; RN also overloads this API
  // for announcement events with a different callback and native emitter type.
  jest.spyOn(AccessibilityInfo, 'addEventListener').mockImplementation(((_event: string, callback: (enabled: boolean) => void) => {
    mockPreferenceListeners.add(callback);
    return { remove: () => { mockPreferenceListeners.delete(callback); } };
  }) as unknown as typeof AccessibilityInfo.addEventListener);
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, callback) => {
    mockLifecycleListeners.add(callback);
    return { remove: () => { mockLifecycleListeners.delete(callback); } };
  });
});

afterEach(() => {
  (AppState as unknown as { currentState: typeof originalAppState }).currentState = originalAppState;
  jest.restoreAllMocks();
  jest.useRealTimers();
});

test('keeps route state mounted but inaccessible during launch, then reveals it without replay on updates', async () => {
  const mounted = jest.fn();
  const unmounted = jest.fn();
  function Destination({ label }: { label: string }) {
    useEffect(() => { mounted(); return unmounted; }, []);
    return <Text>{label}</Text>;
  }
  const screen = await render(
    <AppLaunchGate appReady><Destination label="Account A trip" /></AppLaunchGate>,
  );
  expect(mounted).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('Account A trip')).toBeNull();
  expect(screen.getByText('Account A trip', hidden)).toBeTruthy();
  expect(mockPlayer.play).not.toHaveBeenCalled();
  await fireEvent(screen.getByTestId('app-launch-screen'), 'layout');
  expect(mockHideAsync).toHaveBeenCalledTimes(1);
  expect(mockPlayer.play).toHaveBeenCalledTimes(1);
  await fireEvent(screen.getByTestId('launch-video', hidden), 'firstFrameRender');
  await advance(5_000);
  expect(screen.getByTestId('app-launch-screen')).toBeTruthy();
  await emitPlayer('playToEnd');
  await advance(650);
  expect(screen.queryByTestId('app-launch-screen')).toBeNull();
  expect(screen.getByText('Account A trip')).toBeTruthy();
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);

  await screen.rerender(<AppLaunchGate appReady><Destination label="Account B documents" /></AppLaunchGate>);
  expect(screen.getByText('Account B documents')).toBeTruthy();
  expect(screen.queryByTestId('app-launch-screen')).toBeNull();
  expect(mockCreatePlayer).toHaveBeenCalledTimes(1);
  expect(mounted).toHaveBeenCalledTimes(1);
  expect(unmounted).not.toHaveBeenCalled();
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test('holds the centered completed-logo poster while bootstrap is still pending', async () => {
  const screen = await openLaunch(false);
  await emitPlayer('playToEnd');
  await advance(650);
  expect(screen.getByTestId('launch-poster', hidden).props.resizeMode).toBe('contain');
  expect(screen.queryByTestId('launch-video', hidden)).toBeNull();
  expect(screen.queryByText('Application destination')).toBeNull();
  expect(mockMarkInteractive).not.toHaveBeenCalled();
  expect(Animated.timing).not.toHaveBeenCalled();
  await screen.rerender(<AppLaunchGate appReady><Text>Application destination</Text></AppLaunchGate>);
  expect(screen.getByTestId('app-launch-screen')).toBeTruthy();
  expect(Animated.timing).toHaveBeenCalledTimes(1);
  await advance(650);
  expect(screen.getByText('Application destination')).toBeTruthy();
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test('crossfades the final logo for650ms and hands off touch and accessibility only after completion', async () => {
  const pressed = jest.fn();
  const screen = await render(
    <AppLaunchGate appReady>
      <Pressable testID="destination-action" accessibilityRole="button" onPress={pressed}>
        <Text>Open trip</Text>
      </Pressable>
    </AppLaunchGate>,
  );
  await fireEvent(screen.getByTestId('app-launch-screen'), 'layout');
  await fireEvent(screen.getByTestId('launch-video', hidden), 'firstFrameRender');
  await emitPlayer('playToEnd');
  expect(Animated.timing).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({
    duration: 650, useNativeDriver: true, isInteraction: false, toValue: 1,
  }));
  expect(screen.getByTestId('launch-poster', hidden)).toBeTruthy();
  expect(screen.queryByTestId('launch-video', hidden)).toBeNull();
  await advance(325);
  expect(screen.getByTestId('app-launch-screen')).toBeTruthy();
  expect(screen.getByTestId('app-launch-content', hidden).props).toMatchObject({
    pointerEvents: 'none', accessibilityElementsHidden: true, importantForAccessibility: 'no-hide-descendants',
  });
  expect(screen.queryByText('Open trip')).toBeNull();
  await fireEvent.press(screen.getByTestId('destination-action', hidden));
  expect(pressed).not.toHaveBeenCalled();
  expect(mockMarkInteractive).not.toHaveBeenCalled();
  await advance(324);
  expect(screen.getByTestId('app-launch-screen')).toBeTruthy();
  await advance(1);
  expect(screen.queryByTestId('app-launch-screen')).toBeNull();
  expect(screen.getByTestId('app-launch-content').props).toMatchObject({
    pointerEvents: 'auto', accessibilityElementsHidden: false, importantForAccessibility: 'auto',
  });
  await fireEvent.press(screen.getByRole('button', { name: 'Open trip' }));
  expect(pressed).toHaveBeenCalledTimes(1);
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test.each(['reduced motion', 'background'])('interrupts an ongoing crossfade immediately for %s', async (reason) => {
  const screen = await openLaunch();
  await emitPlayer('playToEnd');
  await advance(300);
  const transition = mockTransitions.at(-1);
  expect(transition).toBeDefined();
  await act(async () => {
    if (reason === 'reduced motion') {
      for (const listener of mockPreferenceListeners) listener(true);
    } else {
      (AppState as unknown as { currentState: string }).currentState = 'background';
      for (const listener of mockLifecycleListeners) listener('background');
    }
  });
  expect(transition?.stop).toHaveBeenCalledTimes(1);
  expect(screen.queryByTestId('app-launch-screen')).toBeNull();
  expect(screen.getByText('Application destination')).toBeTruthy();
  await advance(1_000);
  expect(Animated.timing).toHaveBeenCalledTimes(1);
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test('stops an unfinished crossfade on unmount without a late interactive callback', async () => {
  const screen = await openLaunch();
  await emitPlayer('playToEnd');
  await advance(300);
  const transition = mockTransitions.at(-1);
  expect(transition).toBeDefined();
  await screen.unmount();
  expect(transition?.stop).toHaveBeenCalledTimes(1);
  await advance(1_000);
  expect(mockMarkInteractive).not.toHaveBeenCalled();
});

test('configures a centered silent one-shot player without native playback controls', async () => {
  const screen = await openLaunch();
  expect(mockCreatePlayer).toHaveBeenCalledWith(402);
  expect(mockPlayer).toMatchObject({
    loop: false, muted: true, volume: 0, audioMixingMode: 'mixWithOthers',
    allowsExternalPlayback: false, showNowPlayingNotification: false, staysActiveInBackground: false,
  });
  expect(screen.getByTestId('launch-video', hidden).props).toMatchObject({
    contentFit: 'contain', surfaceType: 'textureView', nativeControls: false,
    fullscreenOptions: { enable: false }, allowsPictureInPicture: false, allowsVideoFrameAnalysis: false,
  });
  await screen.unmount();
});

test('physical devices start with the bundled 4K master and do not downgrade after successful playback', async () => {
  mockIsDevice = true;
  const screen = await openLaunch();
  expect(mockCreatePlayer).toHaveBeenCalledWith(401);
  await fireEvent(screen.getByTestId('launch-video', hidden), 'firstFrameRender');
  await emitPlayer('playToEnd');
  await advance(650);
  expect(screen.getByText('Application destination')).toBeTruthy();
  expect(mockCreatePlayer).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test('retries a physical decoder error once with the compatible clip and removes the old listeners', async () => {
  mockIsDevice = true;
  const screen = await openLaunch();
  const oldSubscriptions = mockPlayer.addListener.mock.results.map((result) => result.value);
  await emitPlayer('statusChange', { status: 'error' });
  expect(mockCreatePlayer.mock.calls).toEqual([[401], [402]]);
  expect(screen.getByTestId('app-launch-screen')).toBeTruthy();
  const newListeners = [...mockPlayerListeners.values()].flatMap((callbacks) => [...callbacks]);
  expect(newListeners).toHaveLength(2);
  for (const subscription of oldSubscriptions) expect(subscription.remove).toHaveBeenCalledTimes(1);
  await fireEvent(screen.getByTestId('launch-video', hidden), 'firstFrameRender');
  await emitPlayer('playToEnd');
  await advance(650);
  expect(screen.getByText('Application destination')).toBeTruthy();
  expect([...mockPlayerListeners.values()].every((callbacks) => callbacks.size === 0)).toBe(true);
  await screen.unmount();
});

test('retries a 4K first-frame timeout then exits if the compatible decoder also times out', async () => {
  mockIsDevice = true;
  const screen = await openLaunch();
  await advance(2_500);
  expect(mockCreatePlayer.mock.calls).toEqual([[401], [402]]);
  expect(screen.getByTestId('app-launch-screen')).toBeTruthy();
  await advance(2_499);
  expect(screen.getByTestId('app-launch-screen')).toBeTruthy();
  await advance(1);
  await advance(650);
  expect(screen.getByText('Application destination')).toBeTruthy();
  expect(mockCreatePlayer).toHaveBeenCalledTimes(2);
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test('retries a thrown 4K play failure using the compatible player', async () => {
  mockIsDevice = true;
  mockPlayer.play.mockImplementationOnce(() => { throw new Error('Unsupported 4K decoder'); });
  const screen = await openLaunch();
  expect(mockCreatePlayer.mock.calls).toEqual([[401], [402]]);
  expect(mockPlayer.play).toHaveBeenCalledTimes(2);
  expect(screen.getByTestId('app-launch-screen')).toBeTruthy();
  await emitPlayer('playToEnd');
  await advance(650);
  expect(screen.getByText('Application destination')).toBeTruthy();
  await screen.unmount();
});

test('a compatible decoder error ends the launch instead of starting another retry', async () => {
  mockIsDevice = true;
  const screen = await openLaunch();
  await emitPlayer('statusChange', { status: 'error' });
  await emitPlayer('statusChange', { status: 'error' });
  await advance(650);
  expect(mockCreatePlayer.mock.calls).toEqual([[401], [402]]);
  expect(screen.getByText('Application destination')).toBeTruthy();
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await advance(12_000);
  expect(mockCreatePlayer).toHaveBeenCalledTimes(2);
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test('starts playback after native splash dismissal settles, including a rejected dismissal', async () => {
  let rejectHide: ((reason: Error) => void) | undefined;
  mockHideAsync.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectHide = reject; }));
  const screen = await openLaunch();
  expect(mockPlayer.play).not.toHaveBeenCalled();
  await act(async () => { rejectHide?.(new Error('Native splash already hidden')); });
  expect(mockPlayer.play).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test.each(['status error', 'play failure', 'construction failure'])('fails open on %s without exposing decoder details', async (failure) => {
  jest.spyOn(console, 'error').mockImplementation(() => undefined);
  if (failure === 'construction failure') mockConstructionFails = true;
  if (failure === 'play failure') mockPlayer.play.mockImplementationOnce(() => { throw new Error('Playback failed'); });
  const screen = await render(<AppLaunchGate appReady><Text>Application destination</Text></AppLaunchGate>);
  const launch = screen.queryByTestId('app-launch-screen');
  if (launch) await fireEvent(launch, 'layout');
  if (failure === 'status error') await emitPlayer('statusChange', { status: 'error' });
  await advance(650);
  expect(screen.getByText('Application destination')).toBeTruthy();
  expect(screen.queryByTestId('app-launch-screen')).toBeNull();
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test('exits after a bounded decoder load timeout when no first frame arrives', async () => {
  const screen = await openLaunch();
  await advance(2_499);
  expect(screen.getByTestId('app-launch-screen')).toBeTruthy();
  await advance(1);
  await advance(650);
  expect(screen.getByText('Application destination')).toBeTruthy();
  await screen.unmount();
});

test('handles a decoder already in error before event listeners are attached', async () => {
  mockPlayer.status = 'error';
  const screen = await render(<AppLaunchGate appReady><Text>Application destination</Text></AppLaunchGate>);
  await advance(650);
  expect(screen.getByText('Application destination')).toBeTruthy();
  expect(mockHideAsync).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test('exits a stalled playback even when the native end event is missing', async () => {
  const screen = await openLaunch();
  await fireEvent(screen.getByTestId('launch-video', hidden), 'firstFrameRender');
  await advance(6_000);
  await advance(650);
  expect(screen.getByText('Application destination')).toBeTruthy();
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test.each(['enabled', 'unavailable'])('skips animation and dismisses native splash before layout when reduced motion is %s', async (preference) => {
  const readPreference = jest.mocked(AccessibilityInfo.isReduceMotionEnabled);
  if (preference === 'enabled') readPreference.mockResolvedValue(true);
  else readPreference.mockRejectedValue(new Error('Accessibility unavailable'));
  const screen = await render(<AppLaunchGate appReady><Text>Application destination</Text></AppLaunchGate>);
  expect(screen.getByText('Application destination')).toBeTruthy();
  expect(mockCreatePlayer).not.toHaveBeenCalled();
  expect(mockHideAsync).toHaveBeenCalledTimes(1);
  expect(Animated.timing).not.toHaveBeenCalled();
  await screen.unmount();
});

test('watchdog dismisses launch and native splash when preference resolution and layout never arrive', async () => {
  jest.mocked(AccessibilityInfo.isReduceMotionEnabled).mockImplementation(() => new Promise(() => undefined));
  const screen = await render(<AppLaunchGate appReady><Text>Application destination</Text></AppLaunchGate>);
  await advance(12_000);
  expect(screen.getByText('Application destination')).toBeTruthy();
  expect(mockHideAsync).toHaveBeenCalledTimes(1);
  expect(mockCreatePlayer).not.toHaveBeenCalled();
  await screen.unmount();
});

test('finishes when backgrounded and does not replay on foreground or account changes', async () => {
  const screen = await openLaunch();
  await act(async () => { for (const listener of mockLifecycleListeners) listener('background'); });
  expect(screen.getByText('Application destination')).toBeTruthy();
  await act(async () => { for (const listener of mockLifecycleListeners) listener('active'); });
  await screen.rerender(<AppLaunchGate appReady><Text>Another account destination</Text></AppLaunchGate>);
  expect(screen.getByText('Another account destination')).toBeTruthy();
  expect(mockCreatePlayer).toHaveBeenCalledTimes(1);
  expect(mockPlayer.play).toHaveBeenCalledTimes(1);
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test('ends an in-progress launch as soon as reduced motion is enabled', async () => {
  const screen = await openLaunch();
  await act(async () => { for (const listener of mockPreferenceListeners) listener(true); });
  expect(screen.getByText('Application destination')).toBeTruthy();
  expect(screen.queryByTestId('launch-video', hidden)).toBeNull();
  await screen.unmount();
});

test('does not start a launch video when the application mounts in the background', async () => {
  (AppState as unknown as { currentState: string }).currentState = 'background';
  const screen = await render(<AppLaunchGate appReady><Text>Application destination</Text></AppLaunchGate>);
  expect(screen.getByText('Application destination')).toBeTruthy();
  expect(mockPlayer.play).not.toHaveBeenCalled();
  expect(mockHideAsync).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test.each(['inactive', null, 'unknown'])('waits for active on a %s cold start instead of skipping or playing unseen', async (initialState) => {
  (AppState as unknown as { currentState: string | null }).currentState = initialState;
  const screen = await openLaunch();
  expect(mockHideAsync).toHaveBeenCalledTimes(1);
  expect(mockPlayer.play).not.toHaveBeenCalled();
  expect(mockPlayer.pause).toHaveBeenCalled();
  // Loading timeout must not run while iOS has not entered the foreground.
  await advance(3_000);
  expect(screen.getByTestId('app-launch-screen')).toBeTruthy();
  expect(screen.queryByText('Application destination')).toBeNull();
  await act(async () => {
    (AppState as unknown as { currentState: string }).currentState = 'active';
    for (const listener of mockLifecycleListeners) listener('active');
  });
  expect(mockPlayer.play).toHaveBeenCalledTimes(1);
  expect(mockCreatePlayer).toHaveBeenCalledTimes(1);
  await fireEvent(screen.getByTestId('launch-video', hidden), 'firstFrameRender');
  await emitPlayer('playToEnd');
  await advance(650);
  expect(screen.getByText('Application destination')).toBeTruthy();
  await screen.unmount();
});

test('pauses a temporary inactive interruption and resumes the same player when active', async () => {
  const screen = await openLaunch();
  await fireEvent(screen.getByTestId('launch-video', hidden), 'firstFrameRender');
  await advance(1_000);
  mockPlayer.pause.mockClear();
  await act(async () => {
    (AppState as unknown as { currentState: string }).currentState = 'inactive';
    for (const listener of mockLifecycleListeners) listener('inactive');
  });
  expect(mockPlayer.pause).toHaveBeenCalledTimes(1);
  await advance(3_000);
  expect(screen.getByTestId('launch-video', hidden)).toBeTruthy();
  expect(screen.queryByText('Application destination')).toBeNull();
  await act(async () => {
    (AppState as unknown as { currentState: string }).currentState = 'active';
    for (const listener of mockLifecycleListeners) listener('active');
  });
  expect(mockPlayer.play).toHaveBeenCalledTimes(2);
  expect(mockCreatePlayer).toHaveBeenCalledTimes(1);
  await emitPlayer('playToEnd');
  await advance(650);
  expect(screen.getByText('Application destination')).toBeTruthy();
  await screen.unmount();
});

test('reconciles an active transition between initial render and listener registration', async () => {
  (AppState as unknown as { currentState: string }).currentState = 'inactive';
  jest.mocked(AppState.addEventListener).mockImplementation((_event, callback) => {
    mockLifecycleListeners.add(callback);
    // Model an already-applied native transition whose event preceded our listener.
    (AppState as unknown as { currentState: string }).currentState = 'active';
    return { remove: () => { mockLifecycleListeners.delete(callback); } };
  });
  const screen = await openLaunch();
  expect(mockPlayer.play).toHaveBeenCalledTimes(1);
  expect(mockCreatePlayer).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test('cleans up launch timers and listeners on unmount without marking an inaccessible app interactive', async () => {
  const screen = await openLaunch(false);
  await screen.unmount();
  expect(mockLifecycleListeners.size).toBe(0);
  expect(mockPreferenceListeners.size).toBe(0);
  expect([...mockPlayerListeners.values()].every((listeners) => listeners.size === 0)).toBe(true);
  await advance(10_000);
  expect(mockMarkInteractive).not.toHaveBeenCalled();
});

const welcomeLogoTarget: LaunchRect = { x: 124, y: 108, width: 142, height: 48 };
let welcomeProgress: Animated.Value | undefined;

function WelcomeDestination({ target = welcomeLogoTarget, label = 'Your trip' }: {
  target?: LaunchRect | null;
  label?: string;
}) {
  const choreography = useContext(LaunchChoreographyContext);
  const registerLogo = choreography?.registerLogo;
  const progress = choreography?.progress;
  useEffect(() => { welcomeProgress = progress; }, [progress]);
  useEffect(() => { registerLogo?.(target); }, [registerLogo, target]);
  return <>
    <LaunchLogoAnchor />
    <LaunchEntrance order={0}><Text>{label}</Text></LaunchEntrance>
    <LaunchEntrance order={1}><Pressable accessibilityRole="button"><Text>Continue</Text></Pressable></LaunchEntrance>
  </>;
}

test('holds the last frame then docks the same logo while the welcome cards rise in sequence', async () => {
  const screen = await render(<AppLaunchGate appReady welcomeExpected><WelcomeDestination /></AppLaunchGate>);
  await fireEvent(screen.getByTestId('app-launch-screen'), 'layout');
  const anchor = screen.getByTestId('launch-logo-anchor', hidden);
  expect(StyleSheet.flatten(anchor.props.style)).toMatchObject({ width: 142, height: 48 });
  expect(StyleSheet.flatten(anchor.props.children.props.style)).toMatchObject({ opacity: 0 });
  expect(StyleSheet.flatten(screen.getByTestId('app-launch-content', hidden).props.style)).toMatchObject({ opacity: 1 });
  expect(screen.queryByText('Your trip')).toBeNull();
  expect(screen.getByTestId('launch-entrance-0', hidden)).toHaveStyle({ opacity: 0, transform: [{ translateY: 96 }] });
  expect(screen.getByTestId('launch-entrance-1', hidden)).toHaveStyle({ opacity: 0, transform: [{ translateY: 96 }] });
  for (const order of [0, 1]) {
    expect(screen.getByTestId(`launch-entrance-${order}`, hidden).props).toMatchObject({
      needsOffscreenAlphaCompositing: true, renderToHardwareTextureAndroid: true,
    });
  }
  await emitPlayer('playToEnd');
  expect(screen.queryByTestId('launch-video', hidden)).toBeNull();
  expect(Animated.timing).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({
    duration: 1_050, delay: 160, useNativeDriver: true, isInteraction: false,
  }));
  expect(screen.getByTestId('app-launch-screen')).toHaveStyle({ opacity: 1 });
  await advance(160);
  expect(screen.getByTestId('app-launch-screen')).toBeTruthy();
  const dock = launchDockGeometry({ x: 0, y: 0, width: 390, height: 844 }, welcomeLogoTarget);
  expect(dock).not.toBeNull();
  await act(async () => { welcomeProgress?.setValue(0.72); });
  expect(screen.getByTestId('app-launch-screen')).toHaveStyle({
    opacity: 1,
    transform: [{ translateX: dock!.translateX }, { translateY: dock!.translateY }, { scale: dock!.scale }],
  });
  await act(async () => { welcomeProgress?.setValue(0.87); });
  expect(screen.getByTestId('launch-entrance-0', hidden)).toHaveStyle({ opacity: 1, transform: [{ translateY: 0 }] });
  expect(screen.getByTestId('app-launch-content', hidden).props.pointerEvents).toBe('none');
  await advance(1_049);
  expect(screen.getByTestId('app-launch-screen')).toBeTruthy();
  await advance(1);
  expect(screen.queryByTestId('app-launch-screen')).toBeNull();
  expect(screen.getByText('Your trip')).toBeTruthy();
  expect(StyleSheet.flatten(screen.getByTestId('launch-logo-anchor').props.children.props.style).opacity).toBeUndefined();
  expect(screen.getByTestId('app-launch-content').props.pointerEvents).toBe('auto');
  for (const order of [0, 1]) {
    expect(screen.getByTestId(`launch-entrance-${order}`).props).toMatchObject({
      needsOffscreenAlphaCompositing: false, renderToHardwareTextureAndroid: false,
    });
  }
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await screen.rerender(<AppLaunchGate appReady welcomeExpected><WelcomeDestination label="Ready to travel" /></AppLaunchGate>);
  expect(screen.getByText('Ready to travel')).toBeTruthy();
  expect(mockCreatePlayer).toHaveBeenCalledTimes(1);
  expect(Animated.timing).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test.each([
  ['missing', null],
  ['outside the screen', { x: 400, y: 108, width: 142, height: 48 }],
] as const)('uses a bounded fade when the welcome logo target is %s', async (_description, target) => {
  const screen = await render(<AppLaunchGate appReady welcomeExpected><WelcomeDestination target={target} /></AppLaunchGate>);
  await fireEvent(screen.getByTestId('app-launch-screen'), 'layout');
  await emitPlayer('playToEnd');
  expect(Animated.timing).not.toHaveBeenCalled();
  await advance(649);
  expect(Animated.timing).not.toHaveBeenCalled();
  await advance(1);
  expect(Animated.timing).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ duration: 650, delay: 0 }));
  await advance(650);
  expect(screen.getByText('Your trip')).toBeTruthy();
  expect(screen.queryByTestId('app-launch-screen')).toBeNull();
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test('accepts a late measured logo before the bounded destination wait expires', async () => {
  const screen = await render(<AppLaunchGate appReady welcomeExpected><WelcomeDestination target={null} /></AppLaunchGate>);
  await fireEvent(screen.getByTestId('app-launch-screen'), 'layout');
  await emitPlayer('playToEnd');
  await advance(500);
  await screen.rerender(<AppLaunchGate appReady welcomeExpected><WelcomeDestination /></AppLaunchGate>);
  expect(Animated.timing).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ duration: 1_050, delay: 160 }));
  await advance(1_210);
  expect(screen.getByText('Your trip')).toBeTruthy();
  expect(Animated.timing).toHaveBeenCalledTimes(1);
  await screen.unmount();
});

test.each(['reduced motion', 'background'])('settles an interrupted logo docking for %s without replay on return', async (reason) => {
  const screen = await render(<AppLaunchGate appReady welcomeExpected><WelcomeDestination /></AppLaunchGate>);
  await fireEvent(screen.getByTestId('app-launch-screen'), 'layout');
  await emitPlayer('playToEnd');
  await advance(400);
  const transition = mockTransitions.at(-1);
  await act(async () => {
    if (reason === 'reduced motion') for (const callback of mockPreferenceListeners) callback(true);
    else for (const callback of mockLifecycleListeners) callback('background');
  });
  expect(transition?.stop).toHaveBeenCalledTimes(1);
  expect(screen.queryByTestId('app-launch-screen')).toBeNull();
  expect(screen.getByText('Your trip')).toBeTruthy();
  await act(async () => { for (const callback of mockLifecycleListeners) callback('active'); });
  await advance(2_000);
  expect(Animated.timing).toHaveBeenCalledTimes(1);
  expect(mockCreatePlayer).toHaveBeenCalledTimes(1);
  expect(mockMarkInteractive).toHaveBeenCalledTimes(1);
  await screen.unmount();
});
