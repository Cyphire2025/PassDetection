import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';

import { useSessionStore } from '@/core/auth/session-store';
import { navigationAnimation, useReducedMotion } from '@/design/accessibility/use-reduced-motion';
import { ApplicationErrorBoundary } from '@/core/errors/application-error-boundary';
import { initializeMobileObservability } from '@/core/observability/mobile-observability';
import { AppProviders } from '@/providers/app-providers';

initializeMobileObservability();
void SplashScreen.preventAutoHideAsync().catch(() => undefined);

export default function RootLayout() {
  return (
    <ApplicationErrorBoundary>
      <RootNavigation />
    </ApplicationErrorBoundary>
  );
}

export function RootNavigation() {
  const reduceMotion = useReducedMotion();
  const principalType = useSessionStore((state) => state.session?.principal.principalType ?? null);
  return (
    <AppProviders>
      <Stack screenOptions={{ headerShown: false, animation: navigationAnimation(reduceMotion, 'fade') }}>
        <Stack.Screen name="index" />
        <Stack.Screen name="activate" />
        <Stack.Screen name="(auth)" />
        <Stack.Protected guard={principalType === 'passenger'}>
          <Stack.Screen name="(passenger)" />
          <Stack.Screen name="document/[id]" />
        </Stack.Protected>
        <Stack.Protected guard={principalType === 'client_manager'}>
          <Stack.Screen name="(manager)" />
        </Stack.Protected>
        <Stack.Protected guard={principalType === 'coordinator'}>
          <Stack.Screen name="(coordinator)" />
        </Stack.Protected>
      </Stack>
    </AppProviders>
  );
}
