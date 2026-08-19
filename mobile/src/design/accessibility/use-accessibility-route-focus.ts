import { useFocusEffect } from 'expo-router';
import { useCallback, type RefObject } from 'react';
import {
  AccessibilityInfo,
  findNodeHandle,
  InteractionManager,
  type Text,
} from 'react-native';

export type AccessibilityFocusServices = Readonly<{
  isScreenReaderEnabled: () => Promise<boolean>;
  findNode: (target: unknown) => number | null;
  setFocus: (reactTag: number) => void;
}>;

const nativeFocusServices: AccessibilityFocusServices = {
  isScreenReaderEnabled: () => AccessibilityInfo.isScreenReaderEnabled(),
  findNode: (target) => findNodeHandle(target as Text),
  setFocus: (reactTag) => AccessibilityInfo.setAccessibilityFocus(reactTag),
};

export async function moveAccessibilityFocus(
  target: unknown,
  services: AccessibilityFocusServices = nativeFocusServices,
  cancelled: () => boolean = () => false,
): Promise<boolean> {
  try {
    if (!target || cancelled() || !await services.isScreenReaderEnabled() || cancelled()) {
      return false;
    }
    const reactTag = services.findNode(target);
    if (reactTag === null || cancelled()) return false;
    services.setFocus(reactTag);
    return true;
  } catch {
    // Accessibility services can disappear during a route/native transition.
    // Focus enhancement must never make the route itself unavailable.
    return false;
  }
}

export function useAccessibilityRouteFocus(target: RefObject<Text | null>): void {
  useFocusEffect(useCallback(() => {
    let cancelled = false;
    const interaction = InteractionManager.runAfterInteractions(() => {
      void moveAccessibilityFocus(
        target.current,
        nativeFocusServices,
        () => cancelled,
      );
    });
    return () => {
      cancelled = true;
      interaction.cancel();
    };
  }, [target]));
}
