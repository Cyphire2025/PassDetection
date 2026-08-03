import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
import * as ScreenCapture from 'expo-screen-capture';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  AppState,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Pdf from 'react-native-pdf';

import { ApiError } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { userFacingErrorMessage } from '@/core/errors/user-facing-error';
import {
  decryptDocumentForViewing,
  isLocalOfflineCiphertextError,
  removeTemporaryView,
} from '@/core/storage/vault';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import { cacheDocument, getDocument } from '@/features/content/data/content-repository';
import { useCoordinatorTripStore } from '@/features/coordinator/state/coordinator-trip-store';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

type TemporaryView = Awaited<ReturnType<typeof decryptDocumentForViewing>>;
type ViewerFailure = { message: string; retryable: boolean };
type OpenOperation = { key: string; promise: Promise<void>; controller: AbortController };

class TerminalDocumentViewerError extends Error {}

function viewerFailure(error: unknown): ViewerFailure {
  const localCiphertextFailure = isLocalOfflineCiphertextError(error);
  const internalMessage = error instanceof Error ? error.message : '';
  const terminalApiFailure = error instanceof ApiError
    && (error.status === 403 || error.status === 404 || error.status === 410);
  const terminalMessage = (
    /no longer available|revoked|not authorized|integrity verification|checksum.*(?:did not match|mismatch)|invalid document checksum/i
  ).test(internalMessage);
  return {
    message: error instanceof TerminalDocumentViewerError
      ? error.message
      : userFacingErrorMessage(error, 'The document could not be opened securely.'),
    retryable: localCiphertextFailure
      || !(error instanceof TerminalDocumentViewerError || terminalApiFailure || terminalMessage),
  };
}

export default function SecureDocumentScreen() {
  const { id, tripId } = useLocalSearchParams<{ id: string; tripId: string }>();
  const session = useSessionStore((state) => state.session);
  const [uri, setUri] = useState<string | null>(null);
  const [contentType, setContentType] = useState<string | null>(null);
  const [title, setTitle] = useState('Secure document');
  const [error, setError] = useState<ViewerFailure | null>(null);
  const [opening, setOpening] = useState(true);
  const mounted = useRef(false);
  const attempt = useRef(0);
  const temporaryView = useRef<TemporaryView | null>(null);
  const openInFlight = useRef<OpenOperation | null>(null);
  const suspendedByLifecycle = useRef(false);

  ScreenCapture.usePreventScreenCapture(`document-${tripId ?? 'unknown'}-${id ?? 'unknown'}`);

  const cleanupTemporaryView = useCallback(() => {
    const temporary = temporaryView.current;
    temporaryView.current = null;
    if (!temporary) return;
    try {
      removeTemporaryView(temporary);
    } catch {
      // Cleanup is best-effort because a file already removed by the native
      // renderer must not trap the viewer in a second failure.
    }
  }, []);

  const openDocument = useCallback((): Promise<void> => {
    const operationKey = `${session?.sessionId ?? 'anonymous'}:${tripId ?? 'missing'}:${id ?? 'missing'}`;
    const existing = openInFlight.current;
    if (existing?.key === operationKey) return existing.promise;
    existing?.controller.abort();

    const operationAttempt = attempt.current + 1;
    const controller = new AbortController();
    const { signal } = controller;
    attempt.current = operationAttempt;
    cleanupTemporaryView();
    setUri(null);
    setError(null);
    setOpening(true);

    let request!: Promise<void>;
    request = (async () => {
      let createdTemporary: TemporaryView | null = null;
      try {
        if (!id || !tripId || !session) {
          throw new TerminalDocumentViewerError('The document could not be opened.');
        }
        const namespace = principalAccountNamespace(session.principal);
        const selectedTripId = session.principal.principalType === 'coordinator'
          ? (() => {
              const selected = useCoordinatorTripStore.getState();
              return selected.accountKey === namespace ? selected.tripId : null;
            })()
          : useSelectedTripStore.getState().tripId;
        if (selectedTripId !== tripId) {
          throw new TerminalDocumentViewerError(
            'Select this trip before opening its offline documents.',
          );
        }
        const document = await getDocument(tripId, id);
        if (!document || document.revoked_at) {
          throw new TerminalDocumentViewerError('This document is no longer available.');
        }
        if (!mounted.current || attempt.current !== operationAttempt) return;
        if (
          document.metadata_state !== 'ready' ||
          !document.offline_available ||
          !document.size_bytes ||
          !document.checksum_sha256
        ) {
          throw new Error('This document is still being prepared for secure offline access.');
        }
        setTitle(document.display_name);
        setContentType(document.content_type);
        if (!document.offline || document.offlineVersion !== document.version) {
          await cacheDocument(document, undefined, signal);
        }
        if (!mounted.current || attempt.current !== operationAttempt) return;
        const vaultInput = {
          namespace,
          tripId,
          documentId: document.id,
          version: document.version,
          checksumSha256: document.checksum_sha256,
          expectedSizeBytes: document.size_bytes,
          contentType: document.content_type,
        };
        try {
          createdTemporary = await decryptDocumentForViewing(vaultInput, signal);
        } catch (caught) {
          if (!isLocalOfflineCiphertextError(caught)) throw caught;
          // A post-registration bit flip or truncation is repaired from the signed source. The
          // repository atomically unregisters the damaged copy and leaves a durable retry job if
          // connectivity disappears during this attempt.
          await cacheDocument(document, undefined, signal);
          createdTemporary = await decryptDocumentForViewing(vaultInput, signal);
        }
        if (!mounted.current || attempt.current !== operationAttempt) {
          removeTemporaryView(createdTemporary);
          createdTemporary = null;
          return;
        }
        temporaryView.current = createdTemporary;
        setUri(createdTemporary.uri);
        createdTemporary = null;
      } catch (caught) {
        if (createdTemporary) {
          try {
            removeTemporaryView(createdTemporary);
          } catch {
            // Preserve the actionable document failure if cleanup also fails.
          }
        }
        if (mounted.current && attempt.current === operationAttempt) {
          setError(viewerFailure(caught));
        }
      } finally {
        if (openInFlight.current?.promise === request) openInFlight.current = null;
        if (mounted.current && attempt.current === operationAttempt) setOpening(false);
      }
    })();
    openInFlight.current = { key: operationKey, promise: request, controller };
    return request;
  }, [cleanupTemporaryView, id, session, tripId]);

  const handleRendererFailure = useCallback((message: string) => {
    attempt.current += 1;
    openInFlight.current?.controller.abort();
    openInFlight.current = null;
    cleanupTemporaryView();
    setUri(null);
    setOpening(false);
    setError({ message, retryable: true });
  }, [cleanupTemporaryView]);

  useEffect(() => {
    mounted.current = true;
    void openDocument();
    return () => {
      mounted.current = false;
      attempt.current += 1;
      openInFlight.current?.controller.abort();
      openInFlight.current = null;
      cleanupTemporaryView();
    };
  }, [cleanupTemporaryView, openDocument]);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      if (nextState !== 'active') {
        if (suspendedByLifecycle.current) return;
        suspendedByLifecycle.current = true;
        attempt.current += 1;
        openInFlight.current?.controller.abort();
        openInFlight.current = null;
        cleanupTemporaryView();
        setUri(null);
        setError(null);
        setOpening(false);
        return;
      }
      if (!suspendedByLifecycle.current || !mounted.current) return;
      suspendedByLifecycle.current = false;
      void openDocument();
    });
    return () => subscription.remove();
  }, [cleanupTemporaryView, openDocument]);

  const closeDocument = useCallback(() => {
    attempt.current += 1;
    openInFlight.current?.controller.abort();
    openInFlight.current = null;
    cleanupTemporaryView();
    router.back();
  }, [cleanupTemporaryView]);

  return (
    <Screen scroll={false} contentStyle={styles.screen} bottomInset={8}>
      <View style={styles.header}>
        <Pressable accessibilityRole="button" accessibilityLabel="Close document" onPress={closeDocument} style={styles.close}>
          <Text style={styles.closeText}>Close</Text>
        </Pressable>
        <Text numberOfLines={1} style={styles.title}>
          {title}
        </Text>
        <View style={styles.headerSpacer} />
      </View>
      {error ? (
        <GlassCard style={styles.messageCard}>
          <Text accessibilityRole="alert" style={styles.errorTitle}>
            Document unavailable
          </Text>
          <Text style={styles.errorText}>{error.message}</Text>
          {error.retryable ? (
            <PrimaryButton
              label="Retry"
              loading={opening}
              onPress={() => void openDocument()}
            />
          ) : null}
        </GlassCard>
      ) : opening || !uri ? (
        <View accessibilityRole="progressbar" accessibilityLabel="Opening encrypted document" style={styles.loading}>
          <ActivityIndicator color={colors.greenDeep} size="large" />
          <Text style={styles.loadingText}>Verifying and opening the encrypted copy…</Text>
        </View>
      ) : contentType === 'application/pdf' ? (
        <Pdf
          key={uri}
          source={{ uri, cache: false }}
          trustAllCerts={false}
          style={styles.viewer}
          enablePaging={false}
          onError={() => handleRendererFailure('The PDF viewer could not render this file.')}
        />
      ) : (
        <Image
          key={uri}
          source={{ uri }}
          cachePolicy="none"
          contentFit="contain"
          style={styles.viewer}
          accessibilityLabel={title}
          onError={() => handleRendererFailure('The image viewer could not render this file.')}
        />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  header: {
    minHeight: 54,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  close: { minWidth: 64, minHeight: 44, justifyContent: 'center' },
  closeText: { color: colors.greenDeep, fontSize: 16, fontWeight: '700' },
  title: { flex: 1, color: colors.ink, textAlign: 'center', fontWeight: '700' },
  headerSpacer: { width: 64 },
  viewer: { flex: 1, backgroundColor: '#EAF0F2' },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.lg },
  loadingText: { color: colors.inkMuted, fontSize: 15 },
  messageCard: { margin: spacing.lg, gap: spacing.sm, borderRadius: radii.md },
  errorTitle: { color: colors.danger, fontSize: 18, fontWeight: '800' },
  errorText: { color: colors.inkMuted, lineHeight: 21 },
});
