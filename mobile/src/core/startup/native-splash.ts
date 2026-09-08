import * as SplashScreen from 'expo-splash-screen';

let handoffTimer: ReturnType<typeof setTimeout> | null = null;

/** Arm before React mounts: native layout/insets must never hold startup forever. */
export function prepareNativeSplash(): void {
  void SplashScreen.preventAutoHideAsync().catch(() => undefined);
  if (handoffTimer !== null) clearTimeout(handoffTimer);
  handoffTimer = setTimeout(() => { void hideNativeSplash(); }, 1_500);
}

export async function hideNativeSplash(): Promise<void> {
  if (handoffTimer !== null) {
    clearTimeout(handoffTimer);
    handoffTimer = null;
  }
  await SplashScreen.hideAsync().catch(() => undefined);
}
