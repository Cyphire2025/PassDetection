import { QueryClientProvider } from '@tanstack/react-query';
import { Image } from 'expo-image';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect, useLayoutEffect, useRef, type PropsWithChildren } from 'react';
import { AppState, StyleSheet } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { bootstrapApplicationSession } from '@/core/auth/application-bootstrap';
import { clearOfflineAuthorizationBootAnchor } from '@/core/auth/offline-authorization';
import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace } from '@/core/auth/types';
import { isDemoMode } from '@/core/demo/demo-mode';
import { shouldPurgeDiskCacheForAccountTransition } from '@/core/storage/render-cache-policy';
import { purgeTemporaryViews } from '@/core/storage/vault';
import { NotificationRuntime } from '@/core/notifications/notification-runtime';
import { markApplicationInteractive } from '@/core/observability/mobile-observability';
import { LocalizationProvider } from '@/core/localization/localization-provider';
import { mobileQueryClient } from '@/core/query/query-client';
import { ReactNativeQueryRuntime } from '@/core/query/react-native-query-runtime';
import { RealtimeRuntime } from '@/core/realtime/realtime-runtime';
import { SyncRuntime } from '@/core/sync/sync-runtime';
import { purgeManagerDocumentPreviews } from '@/features/manager/data/manager-document-preview';
import { MyPhotosCapabilityRuntime } from '@/features/my-photos/downloads/photo-download-runtime';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

let sensitiveCleanupRequested = false;
let sensitiveDiskCleanupRequested = false;
let sensitiveCleanupInFlight: Promise<void> | null = null;

async function drainSensitiveRenderingCleanup(): Promise<void> {
  while (sensitiveCleanupRequested) {
    sensitiveCleanupRequested = false;
    const includeDiskCache = sensitiveDiskCleanupRequested;
    sensitiveDiskCleanupRequested = false;
  // Decrypted local views use `cachePolicy="none"`. Authenticated remote
  // thumbnails/previews use an account-partitioned cache, which is purged at
  // startup and account boundaries together with any residue from older builds.
    const cleanup: Promise<unknown>[] = [
      purgeTemporaryViews(),
      purgeManagerDocumentPreviews(),
      Image.clearMemoryCache(),
    ];
    // Disk eviction is needed at startup and account boundaries to clean residue
    // from older builds. Foreground/background transitions only clear ephemeral
    // plaintext and memory so they do not cause avoidable storage I/O or discard
    // benign image-cache entries.
    if (includeDiskCache) cleanup.push(Image.clearDiskCache());
    const results = await Promise.allSettled(cleanup);
    if (results.some((result) => result.status === 'rejected')) {
      // Never acknowledge a partially completed privacy cleanup. Preserve an
      // in-memory obligation (including the stronger disk boundary) so the
      // next startup/account/lifecycle trigger retries the full idempotent set.
      // A process restart also retries unconditionally during bootstrap.
      sensitiveCleanupRequested = true;
      sensitiveDiskCleanupRequested ||= includeDiskCache;
      return;
    }
  }
}

async function purgeSensitiveRenderingResidue(includeDiskCache: boolean): Promise<void> {
  sensitiveCleanupRequested = true;
  sensitiveDiskCleanupRequested ||= includeDiskCache;
  if (!sensitiveCleanupInFlight) {
    sensitiveCleanupInFlight = drainSensitiveRenderingCleanup().finally(() => {
      sensitiveCleanupInFlight = null;
    });
  }
  await sensitiveCleanupInFlight;
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

  // Clear account-scoped memory before the next native paint. API and SQLite
  // publication guards remain authoritative for asynchronous work, while this
  // layout boundary prevents a one-frame flash of the previous account.
  useLayoutEffect(() => {
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
      if (active) {
        markApplicationInteractive();
        void SplashScreen.hideAsync().catch(() => undefined);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (demoMode) return;
    const subscription = AppState.addEventListener('change', (nextState) => {
      if (nextState !== 'active') {
        // Trusted-time boot anchors are decrypted, account-bound material.
        // Remove them synchronously at the lifecycle boundary so a background
        // snapshot or lock transition cannot retain usable plaintext.
        clearOfflineAuthorizationBootAnchor();
        void purgeSensitiveRenderingResidue(false);
      }
    });
    return () => subscription.remove();
  }, [demoMode]);

  return (
    <GestureHandlerRootView style={styles.fill}>
      <SafeAreaProvider>
        <LocalizationProvider>
          <QueryClientProvider client={queryClient}>
            <ReactNativeQueryRuntime />
            <SyncRuntime />
            <RealtimeRuntime />
            <NotificationRuntime />
            <MyPhotosCapabilityRuntime />
            {children}
          </QueryClientProvider>
        </LocalizationProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
