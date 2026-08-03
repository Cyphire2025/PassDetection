import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';

import { navigationAnimation, useReducedMotion } from '@/design/accessibility/use-reduced-motion';
import { ApplicationErrorBoundary } from '@/core/errors/application-error-boundary';
import { AppProviders } from '@/providers/app-providers';

void SplashScreen.preventAutoHideAsync().catch(() => undefined);

export default function RootLayout() {
  return (
    <ApplicationErrorBoundary>
      <RootNavigation />
    </ApplicationErrorBoundary>
  );
}

function RootNavigation() {
  const reduceMotion = useReducedMotion();
  return (
    <AppProviders>
      <Stack screenOptions={{ headerShown: false, animation: navigationAnimation(reduceMotion, 'fade') }}>
        <Stack.Screen name="index" />
        <Stack.Screen name="activate" />
        <Stack.Screen name="document/[id]" />
        <Stack.Screen name="(auth)" />
        <Stack.Screen name="(passenger)" />
        <Stack.Screen name="(manager)" />
        <Stack.Screen name="(coordinator)" />
      </Stack>
    </AppProviders>
  );
}
