import NetInfo, { type NetInfoState } from '@react-native-community/netinfo';
import { focusManager, onlineManager } from '@tanstack/react-query';
import { AppState, type AppStateStatus } from 'react-native';

import {
  bindReactNativeQueryLifecycle,
  isReachableNetworkState,
} from '../react-native-query-runtime';

jest.mock('@react-native-community/netinfo', () => ({
  __esModule: true,
  default: {
    addEventListener: jest.fn(),
  },
}));

const connectedState = (overrides: Partial<NetInfoState> = {}): NetInfoState => ({
  type: 'wifi',
  isConnected: true,
  isInternetReachable: true,
  details: {
    isConnectionExpensive: false,
    ssid: null,
    bssid: null,
    strength: null,
    ipAddress: null,
    subnet: null,
    frequency: null,
    linkSpeed: null,
    rxLinkSpeed: null,
    txLinkSpeed: null,
  },
  ...overrides,
} as NetInfoState);

beforeEach(() => {
  jest.restoreAllMocks();
  onlineManager.setOnline(true);
  focusManager.setFocused(undefined);
});

test('requires a connected and reachable native network', () => {
  expect(isReachableNetworkState(connectedState())).toBe(true);
  expect(isReachableNetworkState(connectedState({ isConnected: false }))).toBe(false);
  expect(isReachableNetworkState(connectedState({ isInternetReachable: false }))).toBe(false);
  expect(isReachableNetworkState(connectedState({ isInternetReachable: null }))).toBe(true);
});

test('binds native network and foreground state once and removes both listeners', () => {
  let networkListener: (state: NetInfoState) => void = () => {
    throw new Error('Network listener was not registered');
  };
  let appStateListener: (state: AppStateStatus) => void = () => {
    throw new Error('App state listener was not registered');
  };
  const removeNetwork = jest.fn();
  const removeAppState = jest.fn();
  jest.mocked(NetInfo.addEventListener).mockImplementation((listener) => {
    networkListener = listener;
    return removeNetwork;
  });
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
    appStateListener = listener;
    return { remove: removeAppState };
  });

  const cleanup = bindReactNativeQueryLifecycle();
  expect(focusManager.isFocused()).toBe(AppState.currentState === 'active');

  networkListener(connectedState({ isConnected: false }));
  expect(onlineManager.isOnline()).toBe(false);
  networkListener(connectedState());
  expect(onlineManager.isOnline()).toBe(true);

  appStateListener('background');
  expect(focusManager.isFocused()).toBe(false);
  appStateListener('active');
  expect(focusManager.isFocused()).toBe(true);

  cleanup();
  expect(removeNetwork).toHaveBeenCalledTimes(1);
  expect(removeAppState).toHaveBeenCalledTimes(1);
});
