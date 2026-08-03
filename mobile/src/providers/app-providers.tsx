import { QueryClientProvider } from '@tanstack/react-query';
import { Image } from 'expo-image';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect, useRef, type PropsWithChildren } from 'react';
import { AppState, StyleSheet } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { bootstrapApplicationSession } from '@/core/auth/application-bootstrap';
import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';
import { isDemoMode } from '@/core/demo/demo-mode';
import { shouldPurgeDiskCacheForAccountTransition } from '@/core/storage/render-cache-policy';
import { purgeTemporaryViews } from '@/core/storage/vault';
import { NotificationRuntime } from '@/core/notifications/notification-runtime';
import { mobileQueryClient } from '@/core/query/query-client';
import { ReactNativeQueryRuntime } from '@/core/query/react-native-query-runtime';
import { SyncRuntime } from '@/core/sync/sync-runtime';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

async function purgeSensitiveRenderingResidue(includeDiskCache: boolean): Promise<void> {
  // Personal images are rendered with `cachePolicy="none"`, but clear the
  // renderer caches as well so upgrades from an older build cannot retain a
  // decrypted view outside the managed temporary-view directory.
  const cleanup: Promise<unknown>[] = [
    purgeTemporaryViews(),
    Image.clearMemoryCache(),
  ];
  // Disk eviction is needed at startup and account boundaries to clean residue
  // from older builds. Foreground/background transitions only clear ephemeral
  // plaintext and memory so they do not cause avoidable storage I/O or discard
  // benign image-cache entries.
  if (includeDiskCache) cleanup.push(Image.clearDiskCache());
  await Promise.allSettled(cleanup);
}

export function AppProviders({ children }: PropsWithChildren) {
  const demoMode = isDemoMode();
  const queryClient = mobileQueryClient;
  const agencyId = useSessionStore((state) => state.session?.principal.agencyId ?? null);
  const accountId = useSessionStore((state) => state.session?.principal.accountId ?? null);
  const activeAccount = agencyId && accountId
    ? accountNamespace({ agencyId, accountId })
    : null;
  const previousAccount = useRef<string | null>(null);
  const hasActivatedAccount = useRef(false);

  useEffect(() => {
    if (previousAccount.current !== activeAccount) {
      queryClient.clear();
      useSelectedTripStore.getState().clear();
      const includeDiskCache = shouldPurgeDiskCacheForAccountTransition({
        previousAccount: previousAccount.current,
        nextAccount: activeAccount,
        hasActivatedAccount: hasActivatedAccount.current,
      });
      void purgeSensitiveRenderingResidue(includeDiskCache);
      if (activeAccount) hasActivatedAccount.current = true;
      previousAccount.current = activeAccount;
    }
  }, [activeAccount, queryClient]);

  useEffect(() => {
    let active = true;
    void purgeSensitiveRenderingResidue(true);
    // The application bootstrap boundary always resolves with a structured
    // outcome, so a native SecureStore/SQLite rejection cannot become an
    // unhandled promise or leave the router permanently in `booting`.
    void bootstrapApplicationSession().finally(() => {
      if (active) void SplashScreen.hideAsync().catch(() => undefined);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (demoMode) return;
    const subscription = AppState.addEventListener('change', (nextState) => {
      if (nextState !== 'active') {
        void purgeSensitiveRenderingResidue(false);
      }
    });
    return () => subscription.remove();
  }, [demoMode]);

  return (
    <GestureHandlerRootView style={styles.fill}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <ReactNativeQueryRuntime />
          <SyncRuntime />
          <NotificationRuntime />
          {children}
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
