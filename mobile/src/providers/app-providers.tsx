import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect, useRef, useState, type PropsWithChildren } from 'react';
import { AppState, StyleSheet } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { bootstrapSession } from '@/core/auth/session-service';
import { useSessionStore } from '@/core/auth/session-store';
import { isDemoMode } from '@/core/demo/demo-mode';
import { purgeTemporaryViews } from '@/core/storage/vault';
import { SessionLock } from '@/design/components/session-lock';
import { NotificationRuntime } from '@/core/notifications/notification-runtime';
import { SyncRuntime } from '@/core/sync/sync-runtime';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

export function AppProviders({ children }: PropsWithChildren) {
  const demoMode = isDemoMode();
  const sessionStatus = useSessionStore((state) => state.status);
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60_000,
            gcTime: 10 * 60_000,
            retry: 2,
            refetchOnReconnect: true,
            refetchOnWindowFocus: false,
          },
          mutations: { retry: 0 },
        },
      }),
  );
  const principalId = useSessionStore((state) => state.session?.principal.id ?? null);
  const previousPrincipalId = useRef<string | null>(null);

  useEffect(() => {
    if (previousPrincipalId.current !== principalId) {
      queryClient.clear();
      useSelectedTripStore.getState().clear();
      previousPrincipalId.current = principalId;
    }
  }, [principalId, queryClient]);

  useEffect(() => {
    let active = true;
    purgeTemporaryViews();
    void bootstrapSession().finally(() => {
      if (active) void SplashScreen.hideAsync();
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (demoMode) return;
    const subscription = AppState.addEventListener('change', (nextState) => {
      if (nextState !== 'active') {
        purgeTemporaryViews();
        if (useSessionStore.getState().session) useSessionStore.getState().setLocked();
      }
    });
    return () => subscription.remove();
  }, [demoMode]);

  return (
    <GestureHandlerRootView style={styles.fill}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <SyncRuntime />
          <NotificationRuntime />
          {sessionStatus === 'locked' && !demoMode ? <SessionLock /> : children}
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
