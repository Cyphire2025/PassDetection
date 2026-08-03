import NetInfo, { type NetInfoState } from '@react-native-community/netinfo';
import { focusManager, onlineManager } from '@tanstack/react-query';
import { useEffect } from 'react';
import { AppState } from 'react-native';

export function isReachableNetworkState(state: NetInfoState): boolean {
  return Boolean(state.isConnected && state.isInternetReachable !== false);
}

export function bindReactNativeQueryLifecycle(): () => void {
  focusManager.setFocused(AppState.currentState === 'active');
  const removeNetworkListener = NetInfo.addEventListener((state) => {
    onlineManager.setOnline(isReachableNetworkState(state));
  });
  const appStateSubscription = AppState.addEventListener('change', (state) => {
    focusManager.setFocused(state === 'active');
  });
  return () => {
    removeNetworkListener();
    appStateSubscription.remove();
    focusManager.setFocused(undefined);
  };
}

export function ReactNativeQueryRuntime() {
  useEffect(() => bindReactNativeQueryLifecycle(), []);
  return null;
}
