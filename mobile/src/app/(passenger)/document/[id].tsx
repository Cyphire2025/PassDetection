import { Image } from 'expo-image';
import { router, useLocalSearchParams } from 'expo-router';
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
  releaseTemporaryView,
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
      : userFacingErrorMessage(error, 'The document could not be opened.'),
    retryable: localCiphertextFailure
      || !(error instanceof TerminalDocumentViewerError || terminalApiFailure || terminalMessage),
  };
}

export default function SecureDocumentScreen() {
  const { id, tripId } = useLocalSearchParams<{ id: string; tripId: string }>();
  const session = useSessionStore((state) => state.session);
  const [uri, setUri] = useState<string | null>(null);
  const [contentType, setContentType] = useState<string | null>(null);
  const [title, setTitle] = useState('Document');
  const [error, setError] = useState<ViewerFailure | null>(null);
  const [opening, setOpening] = useState(true);
  const [rendererLoaded, setRendererLoaded] = useState(false);
  const mounted = useRef(false);
  const attempt = useRef(0);
  const temporaryView = useRef<TemporaryView | null>(null);
  const openInFlight = useRef<OpenOperation | null>(null);
  const suspendedByLifecycle = useRef(false);
  const rendererLoadedRef = useRef(false);
  const automaticRendererRetries = useRef(0);

  const finishTemporaryView = useCallback((discard: boolean) => {
    const temporary = temporaryView.current;
    temporaryView.current = null;
    if (!temporary) return;
    try {
      if (discard) removeTemporaryView(temporary);
      else releaseTemporaryView(temporary);
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
    finishTemporaryView(false);
    rendererLoadedRef.current = false;
    setRendererLoaded(false);
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
          throw new Error('This document is still being prepared for offline use.');
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
          releaseTemporaryView(createdTemporary);
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
  }, [finishTemporaryView, id, session, tripId]);

  const handleRendererFailure = useCallback((failedUri: string, message: string) => {
    if (temporaryView.current?.uri !== failedUri) return;
    attempt.current += 1;
    openInFlight.current?.controller.abort();
    openInFlight.current = null;
    finishTemporaryView(true);
    rendererLoadedRef.current = false;
    setRendererLoaded(false);
    setUri(null);
    if (automaticRendererRetries.current < 1 && mounted.current) {
      automaticRendererRetries.current += 1;
      setError(null);
      setOpening(true);
      void openDocument();
      return;
    }
    setOpening(false);
    setError({ message, retryable: true });
  }, [finishTemporaryView, openDocument]);

  const markRendererLoaded = useCallback(() => {
    rendererLoadedRef.current = true;
    setRendererLoaded(true);
  }, []);

  const retryDocument = useCallback(() => {
    automaticRendererRetries.current = 0;
    void openDocument();
  }, [openDocument]);

  useEffect(() => {
    mounted.current = true;
    automaticRendererRetries.current = 0;
    void openDocument();
    return () => {
      mounted.current = false;
      attempt.current += 1;
      openInFlight.current?.controller.abort();
      openInFlight.current = null;
      finishTemporaryView(false);
    };
  }, [finishTemporaryView, openDocument]);

  useEffect(() => {
    if (!uri) return;
    const timeout = setTimeout(() => {
      if (!rendererLoadedRef.current) {
        handleRendererFailure(uri, 'The document viewer took too long to display this file.');
      }
    }, 8_000);
    return () => clearTimeout(timeout);
  }, [handleRendererFailure, uri]);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      if (nextState !== 'active') {
        if (suspendedByLifecycle.current) return;
        suspendedByLifecycle.current = true;
        attempt.current += 1;
        openInFlight.current?.controller.abort();
        openInFlight.current = null;
        finishTemporaryView(true);
        rendererLoadedRef.current = false;
        setRendererLoaded(false);
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
  }, [finishTemporaryView, openDocument]);

  const closeDocument = useCallback(() => {
    attempt.current += 1;
    openInFlight.current?.controller.abort();
    openInFlight.current = null;
    finishTemporaryView(false);
    router.back();
  }, [finishTemporaryView]);

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
              onPress={retryDocument}
            />
          ) : null}
        </GlassCard>
      ) : opening || !uri ? (
        <View accessibilityRole="progressbar" accessibilityLabel="Opening document" style={styles.loading}>
          <ActivityIndicator color={colors.greenDeep} size="large" />
          <Text style={styles.loadingText}>Opening your document…</Text>
        </View>
      ) : contentType === 'application/pdf' ? (
        <View style={styles.viewerContainer}>
          <Pdf
            key={uri}
            source={{ uri, cache: false }}
            trustAllCerts={false}
            style={styles.viewer}
            enablePaging={false}
            onLoadComplete={markRendererLoaded}
            onError={() => handleRendererFailure(uri, 'The PDF viewer could not render this file.')}
          />
          {!rendererLoaded ? (
            <View pointerEvents="none" style={styles.rendererLoading}>
              <ActivityIndicator color={colors.blueDeep} size="large" />
            </View>
          ) : null}
        </View>
      ) : (
        <View style={styles.viewerContainer}>
          <Image
            key={uri}
            source={{ uri }}
            cachePolicy="none"
            contentFit="contain"
            style={styles.viewer}
            accessibilityLabel={title}
            onLoad={markRendererLoaded}
            onError={() => handleRendererFailure(uri, 'The image viewer could not render this file.')}
          />
          {!rendererLoaded ? (
            <View pointerEvents="none" style={styles.rendererLoading}>
              <ActivityIndicator color={colors.blueDeep} size="large" />
            </View>
          ) : null}
        </View>
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
  viewerContainer: { flex: 1, backgroundColor: '#EAF0F2' },
  viewer: { flex: 1, backgroundColor: '#EAF0F2' },
  rendererLoading: {
    position: 'absolute',
    inset: 0,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#EAF0F2',
  },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.lg },
  loadingText: { color: colors.inkMuted, fontSize: 15 },
  messageCard: { margin: spacing.lg, gap: spacing.sm, borderRadius: radii.md },
  errorTitle: { color: colors.danger, fontSize: 18, fontWeight: '800' },
  errorText: { color: colors.inkMuted, lineHeight: 21 },
});
