import * as ScreenCapture from 'expo-screen-capture';
import { useEffect, useState } from 'react';
import { AppState, Platform, StyleSheet, View } from 'react-native';

import { colors } from '@/design/theme';

const protectionLeases = new Map<string, number>();
let totalProtectionLeases = 0;

function runBestEffort(operation: () => Promise<void>): void {
  try {
    void operation().catch(() => undefined);
  } catch {
    // Unsupported native methods must not break document access. The opaque
    // lifecycle overlay remains the fail-safe task-switcher privacy control.
  }
}

function acquireNativeProtection(protectionKey: string): () => void {
  const currentKeyLeases = protectionLeases.get(protectionKey) ?? 0;
  protectionLeases.set(protectionKey, currentKeyLeases + 1);
  totalProtectionLeases += 1;

  if (currentKeyLeases === 0) {
    runBestEffort(() => ScreenCapture.preventScreenCaptureAsync(protectionKey));
  }
  if (totalProtectionLeases === 1 && Platform.OS === 'ios') {
    runBestEffort(() => ScreenCapture.enableAppSwitcherProtectionAsync(1));
  }

  let released = false;
  return () => {
    if (released) return;
    released = true;

    const keyLeases = protectionLeases.get(protectionKey) ?? 0;
    if (keyLeases <= 1) {
      protectionLeases.delete(protectionKey);
      runBestEffort(() => ScreenCapture.allowScreenCaptureAsync(protectionKey));
    } else {
      protectionLeases.set(protectionKey, keyLeases - 1);
    }

    totalProtectionLeases = Math.max(0, totalProtectionLeases - 1);
    if (totalProtectionLeases === 0 && Platform.OS === 'ios') {
      runBestEffort(() => ScreenCapture.disableAppSwitcherProtectionAsync());
    }
  };
}

function useSensitiveScreenProtection(protectionKey: string): boolean {
  const [obscured, setObscured] = useState(AppState.currentState !== 'active');

  useEffect(() => acquireNativeProtection(protectionKey), [protectionKey]);
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      setObscured(state !== 'active');
    });
    return () => subscription.remove();
  }, []);

  return obscured;
}

export function SensitiveScreenProtection({ protectionKey }: { protectionKey: string }) {
  const obscured = useSensitiveScreenProtection(protectionKey);
  if (!obscured) return null;

  return (
    <View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      pointerEvents="auto"
      style={styles.overlay}
      testID="sensitive-screen-privacy-overlay"
    />
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFill,
    backgroundColor: colors.navy,
    elevation: 1000,
    zIndex: 1000,
  },
});
